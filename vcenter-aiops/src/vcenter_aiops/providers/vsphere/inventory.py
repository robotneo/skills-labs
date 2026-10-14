"""Bulk property retrieval; SDK objects remain inside the Provider."""
import math

from ...domain.models import fail


class Inventory:
    def __init__(self, si):
        self.content = si.RetrieveContent()

    @staticmethod
    def _scalar(value):
        # Real vCenter returns 64-bit fields (datastore capacity/freeSpace etc.)
        # as pyVmomi.VmomiSupport.long, an int *subclass*: type(value) is int is
        # False for it, so match by isinstance and exclude bool before int.
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        if isinstance(value, str):
            # pyVmomi enum values subclass str; keep only their plain text value.
            return str.__str__(value)
        fail("query_incomplete", "资产属性包含不支持的数据类型", 4)

    def list(self, kind="vm", limit=100):
        from pyVmomi import vim, vmodl
        kinds = {"vm": vim.VirtualMachine, "template": vim.VirtualMachine, "host": vim.HostSystem,
                 "cluster": vim.ClusterComputeResource, "datastore": vim.Datastore}
        if kind not in kinds or not 1 <= limit <= 1000:
            fail("query_invalid", "不支持的资源类型或分页大小", 2)
        cls = kinds[kind]
        fields = {"template": ["name", "runtime.powerState", "config.instanceUuid", "config.template"],
                  "vm": ["name", "runtime.powerState", "config.instanceUuid", "guest.ipAddress"],
                  "host": ["name", "runtime.connectionState", "runtime.inMaintenanceMode"],
                  "cluster": ["name"], "datastore": ["name", "summary.capacity", "summary.freeSpace"]}[kind]
        pc = vmodl.query.PropertyCollector
        view = self.content.viewManager.CreateContainerView(self.content.rootFolder, [cls], True)
        collector = self.content.propertyCollector
        token = None
        values = []
        truncated = False
        try:
            traversal = pc.TraversalSpec(name="view", type=vim.view.ContainerView, path="view", skip=False)
            spec = pc.FilterSpec(objectSet=[pc.ObjectSpec(obj=view, skip=True, selectSet=[traversal])],
                                 propSet=[pc.PropertySpec(type=cls, all=False, pathSet=fields)])
            page = collector.RetrievePropertiesEx(specSet=[spec], options=pc.RetrieveOptions(maxObjects=limit))
            while page:
                token = page.token
                for index, item in enumerate(page.objects or []):
                    record = {"id": self._scalar(item.obj._moId), "kind": kind}
                    record.update({self._scalar(p.name): self._scalar(p.val) for p in item.propSet or []})
                    record["unavailable"] = [self._scalar(p.path) for p in item.missingSet or []]
                    if kind == "template" and not isinstance(record.get("config.template"), bool):
                        fail("query_incomplete", "模板标记不可读，不能确定模板查询结果", 4)
                    if kind == "template" and record.get("config.template") is not True:
                        continue
                    values.append(record)
                    if len(values) >= limit:
                        truncated = bool(token) or index + 1 < len(page.objects)
                        break
                if len(values) >= limit or not token:
                    break
                page = collector.ContinueRetrievePropertiesEx(token=token)
            return {"items": values, "truncated": truncated}
        finally:
            try:
                if token:
                    collector.CancelRetrievePropertiesEx(token=token)
            finally:
                view.Destroy()

    def resolve(self, kind, name=None, object_id=None):
        # Avoid silently selecting an object from a truncated inventory.
        results = self.list(kind, 1000)
        matches = [row for row in results["items"]
                   if (row["id"] == object_id if object_id else row.get("name") == name)]
        if results["truncated"]:
            fail("query_incomplete", "对象解析超出当前查询范围，不能安全选择目标", 4)
        if not matches:
            fail("target_not_found", "未找到指定对象", 4)
        if len(matches) > 1:
            fail("target_ambiguous", "名称存在多个匹配，请使用对象 ID", 4)
        return matches[0]
