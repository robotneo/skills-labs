"""Fresh triggered alarm reads; no acknowledgement or reset side effects."""
from datetime import datetime, timezone
import re

from ...domain.models import fail


# ClearTriggeredAlarms only filters by managed-object TYPE (never a specific
# entity or alarm). Its AlarmTypeByEntity enum exposes only VM and Host (plus
# All) — there is no cluster/datastore token — so the public surface is
# deliberately limited to those two. Each maps:
#   entity_type -> (WSDL enum token, managed-object moId prefix).
RESET_ENTITY_TYPES = {
    "vm": ("entityTypeVm", ("vm-",)),
    "host": ("entityTypeHost", ("host-",)),
}
RESET_STATUSES = ("red", "yellow")


def _entity_prefix(entity_id):
    for kind, (_, prefixes) in RESET_ENTITY_TYPES.items():
        if any(entity_id.startswith(prefix) for prefix in prefixes):
            return kind
    return None



class Alarms:
    def __init__(self, si):
        self.si = si
        self.content = si.RetrieveContent()

    def exact_state(self, params):
        if not re.fullmatch(r"alarm-\d+", params["alarm_id"]):
            fail("target_invalid", "需要精确 alarm-N 标识", 2)
        data = self.list(entity_id=params["entity_id"], limit=1000)
        if data["truncated"]:
            fail("query_incomplete", "告警查询被截断，不能安全确认目标", 4)
        matches = [s for s in data["items"] if s["entity_id"] == params["entity_id"] and s["alarm_id"] == params["alarm_id"]]
        if len(matches) != 1:
            fail("alarm_not_found", "指定实体上没有唯一匹配的触发告警", 4)
        return matches[0]

    def preflight_acknowledge(self, params):
        about = self.content.about
        if about.apiType != "VirtualCenter" or not re.match(r"^(6\.[57]|7\.0|8\.0)(\.|$)", about.apiVersion) or not about.instanceUuid:
            fail("capability_unsupported", "要求具有唯一身份的目标版本 vCenter", 4)
        state = self.exact_state(params)
        if state["status"] not in ("red", "yellow") or state["acknowledged"] is True:
            fail("precondition_failed", "告警已确认或不处于触发状态", 4)
        return {"target": about.instanceUuid + ":" + params["entity_id"], "server_uuid": about.instanceUuid,
                "object_id": params["entity_id"], "kind": "alarm", "before": state, "risk": "change",
                "scope": {"entity_id": params["entity_id"], "alarm_id": params["alarm_id"], "count": 1}}

    def submit_acknowledge(self, params, binding):
        from pyVmomi import vim
        if self.preflight_acknowledge(params) != binding:
            fail("plan_stale", "告警身份或状态已变化，请重新预览", 4)
        self.content.alarmManager.AcknowledgeAlarm(alarm=vim.alarm.Alarm(params["alarm_id"], self.si._stub),
                                                  entity=vim.ManagedEntity(params["entity_id"], self.si._stub))
        return {"acknowledged": True, "command": "alarm acknowledge"}

    def verify_acknowledge(self, params, binding):
        if self.content.about.instanceUuid != binding["server_uuid"]:
            return False
        state = self.exact_state(params)
        return state["key"] == binding["before"]["key"] and state["triggered_at"] == binding["before"]["triggered_at"] and state["acknowledged"] is True

    # --- Bulk reset via ClearTriggeredAlarms (6.7+) ----------------------
    # The API filters only by managed-object TYPE + status; it cannot target a
    # precise entity or alarm. We therefore bind the *exact matched set* of
    # triggered alarm-state keys into the confirmed plan and verify that set
    # disappears, rather than pretending the operation is single-alarm precise.

    def _reset_candidates(self, params):
        statuses = params["statuses"] if params.get("statuses") is not None else list(RESET_STATUSES)
        entity_type = params["entity_type"]
        type_token, prefixes = RESET_ENTITY_TYPES[entity_type]
        # Read from the root so the filter spans the whole managed-type class.
        data = self.list(entity_id=None, limit=1000)
        if data["truncated"]:
            fail("query_incomplete", "告警查询被截断，不能安全绑定重置范围", 4)
        matched = []
        for item in data["items"]:
            if item["status"] not in statuses:
                continue
            if not any(item["entity_id"].startswith(prefix) for prefix in prefixes):
                continue
            matched.append(item)
        return type_token, statuses, matched

    def preflight_reset(self, params):
        about = self.content.about
        if about.apiType != "VirtualCenter" or not re.match(r"^(6\.[57]|7\.0|8\.0)(\.|$)", about.apiVersion) or not about.instanceUuid:
            fail("capability_unsupported", "要求具有唯一身份的目标版本 vCenter", 4)
        if re.match(r"^6\.5(\.|$)", about.apiVersion):
            fail("capability_unsupported", "ClearTriggeredAlarms 仅支持 vCenter 6.7 及以上；6.5 不提供告警重置", 4)
        if params.get("entity_type") not in RESET_ENTITY_TYPES:
            fail("invalid_arguments", "entity_type 只支持 vm 或 host（接口无集群/数据存储过滤）", 2)
        if "statuses" not in params or params["statuses"] is None:
            statuses = list(RESET_STATUSES)
        else:
            statuses = params["statuses"]
        if not isinstance(statuses, list) or not statuses or any(s not in RESET_STATUSES for s in statuses):
            fail("invalid_arguments", "statuses 只能是 red/yellow 的非空组合", 2)
        if len(set(statuses)) != len(statuses):
            fail("invalid_arguments", "statuses 含重复值", 2)
        type_token, statuses, matched = self._reset_candidates(params)
        if not matched:
            fail("precondition_failed", "过滤条件下没有可重置的触发告警；不会执行空范围的全局写", 4)
        keys = sorted(item["key"] for item in matched)
        return {"target": about.instanceUuid + ":alarms:" + params["entity_type"],
                "server_uuid": about.instanceUuid, "object_id": None, "kind": "alarm-reset",
                "before": {"matched_keys": keys}, "risk": "change",
                "scope": {"entity_type": params["entity_type"], "type_entity": type_token,
                          "statuses": sorted(statuses), "count": len(keys),
                          "entities": sorted({item["entity_id"] for item in matched})},
                "warnings": ["ClearTriggeredAlarms 按受管对象类型+状态批量重置，不能精确定位单个告警或实体",
                             "预览与提交之间若有新告警落入同一过滤范围，也会被一并重置",
                             "重置会清除告警触发状态（含未确认），不代表底层故障已恢复"]}

    def submit_reset(self, params, binding):
        from pyVmomi import vim
        rechecked = self.preflight_reset(params)
        # The matched set may legitimately shrink (alarm cleared on its own);
        # an *expansion* means the bulk write would now hit alarms the operator
        # never confirmed, so require a fresh preview.
        previous = set(binding["before"]["matched_keys"])
        current = set(rechecked["before"]["matched_keys"])
        if current - previous:
            fail("plan_stale", "过滤范围内出现了预览时不存在的新告警，请重新预览确认", 4)
        filter_spec = vim.alarm.AlarmFilterSpec(
            status=[vim.ManagedEntity.Status(s) for s in binding["scope"]["statuses"]],
            typeEntity=binding["scope"]["type_entity"])
        self.content.alarmManager.ClearTriggeredAlarms(filter=filter_spec)
        return {"reset": True, "command": "alarm reset",
                "requested_count": binding["scope"]["count"]}

    def verify_reset(self, params, binding):
        if self.content.about.instanceUuid != binding["server_uuid"]:
            return False
        try:
            _, _, matched = self._reset_candidates({
                "entity_type": binding["scope"]["entity_type"],
                "statuses": binding["scope"]["statuses"]})
        except Exception:
            return False
        present = {item["key"] for item in matched}
        # Every alarm state explicitly bound in the plan must have disappeared.
        return not (set(binding["before"]["matched_keys"]) & present)


    def list(self, entity_id=None, status=None, limit=100):
        from pyVmomi import vim, vmodl
        if type(limit) is not int or not 1 <= limit <= 1000 or status not in (None, "red", "yellow", "green", "gray"):
            fail("query_invalid", "告警状态或数量限制无效", 2)
        entity = self.content.rootFolder
        if entity_id is not None:
            kinds = ((r"vm-\d+", vim.VirtualMachine), (r"host-\d+", vim.HostSystem),
                     (r"domain-c\d+", vim.ClusterComputeResource), (r"datastore-\d+", vim.Datastore),
                     (r"group-[a-z]\d+", vim.Folder), (r"datacenter-\d+", vim.Datacenter))
            cls = next((cls for pattern, cls in kinds if re.fullmatch(pattern, entity_id)), None)
            if cls is None:
                fail("query_invalid", "需要精确受支持的对象 ID；不回退扩大查询范围", 2)
            entity = cls(entity_id, self.si._stub)
        pc = vmodl.query.PropertyCollector
        spec = pc.FilterSpec(objectSet=[pc.ObjectSpec(obj=entity, skip=False)],
                             propSet=[pc.PropertySpec(type=vim.ManagedEntity, all=False, pathSet=["triggeredAlarmState"])])
        collector = self.content.propertyCollector
        page = collector.RetrievePropertiesEx(specSet=[spec], options=pc.RetrieveOptions(maxObjects=1))
        try:
            objects = page.objects if page else []
            if not objects or len(objects) != 1 or objects[0].obj._moId != entity._moId or objects[0].missingSet:
                fail("alarm_query_unavailable", "目标不存在或告警属性不可读取；不能判定没有告警", 4)
            props = {p.name: p.val for p in objects[0].propSet or []}
            if "triggeredAlarmState" not in props:
                fail("alarm_query_unavailable", "未返回告警属性；不能判定没有告警", 4)
            items, truncated = [], bool(page.token)
            for state in props["triggeredAlarmState"] or []:
                if status is not None and str(state.overallStatus) != status:
                    continue
                if len(items) >= limit:
                    truncated = True
                    break
                date = lambda value: value.isoformat() if value is not None else None
                items.append({"key": state.key, "alarm_id": state.alarm._moId, "entity_id": state.entity._moId,
                              "status": str(state.overallStatus), "triggered_at": date(state.time),
                              "acknowledged": state.acknowledged, "acknowledged_by": state.acknowledgedByUser,
                              "acknowledged_at": date(state.acknowledgedTime)})
            return {"items": items, "truncated": truncated, "scope": {"entity_id": entity._moId, "includes_descendants": True},
                    "collected_at": datetime.now(timezone.utc).isoformat(), "untrusted_content": True,
                    "source": "triggeredAlarmState", "warnings": ["只包含当前身份可见的触发告警；空结果不代表环境无故障"]}
        finally:
            if page and page.token:
                collector.CancelRetrievePropertiesEx(token=page.token)
