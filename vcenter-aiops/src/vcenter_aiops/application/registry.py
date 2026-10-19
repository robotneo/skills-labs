from ..domain.contracts import Command, Parameter as P
from ..domain.models import fail
from .registrations import WRITE_OPTIONS
from .registrations.hosts import COMMANDS as HOST_COMMANDS
from .registrations.clusters import COMMANDS as CLUSTER_COMMANDS
from .registrations.creation import COMMANDS as CREATION_COMMANDS
from .registrations.secrets import COMMANDS as SECRET_COMMANDS
from .registrations.history_presets import COMMANDS as HISTORY_PRESET_COMMANDS
from .registrations.policy import COMMANDS as POLICY_COMMANDS
from .registrations.guest import COMMANDS as GUEST_COMMANDS
from .registrations.linked import COMMANDS as LINKED_COMMANDS
from .registrations.ovf import COMMANDS as OVF_COMMANDS

NAME = (P("name", required=True, positional=True),)
LIMIT = (P("limit", "integer", default=100, minimum=1, maximum=1000),)
SELECTOR = (P("id"), P("name"))


def local(path, category, description, parameters=()):
    return Command(path, category, description, "application.commands.local:" + path.replace(" ", "_").replace("-", "_"), parameters, mcp=False)


def query(path, description, parameters=(), one_of=()):
    return Command(path, "remote_read", description, "application.commands.queries:" + path.replace(" ", "_").replace("-", "_"), parameters, one_of)


COMMANDS = (
    local("version", "local_read", "查看开发版本"),
    local("doctor", "local_read", "检查本机依赖，显式 --connect 才连接", (P("connect", "boolean", default=False),)),
    local("capabilities list", "local_read", "查看实现和版本验证状态"),
    local("capabilities show", "local_read", "查看叶子参数 schema 与风险", (P("command_path", required=True, positional=True),)),
    local("profile list", "local_read", "列出连接配置"),
    local("profile show", "local_read", "查看配置，不显示密码", NAME),
    local("profile add", "local_write", "添加连接配置", NAME + (
        P("host", required=True), P("user", required=True), P("password_ref", required=True),
        P("port", "integer", default=443, minimum=1, maximum=65535), P("ca_file"), P("insecure", "boolean", default=False))),
    local("profile update", "local_write", "只更新指定字段", NAME + (
        P("host"), P("user"), P("password_ref"), P("port", "integer", minimum=1, maximum=65535), P("ca_file"), P("insecure", "boolean"))),
    local("profile delete", "local_write", "删除本地配置", NAME),
    query("profile test", "验证连接及服务端身份"),
    local("ip reserve", "local_write", "事务预留网络作用域内 IP", (
        P("scope", required=True), P("ip", required=True), P("owner", required=True), P("minutes", "integer", minimum=1))),
    local("ip release", "local_write", "释放精确租约", (P("lease_id", required=True, positional=True),)),
    local("ip list", "local_read", "列出租约", (P("scope"),)),
    Command("ip check", "remote_read", "汇总资产占用、本地租约与 ping 三路信号；ping 不通不判空闲",
            "application.commands.queries:ip_check", (
                P("address", required=True), P("scope", required=True))),
    Command("ip available", "remote_read", "仅在有正向空闲证据时返回可用，否则不确定，不自动分配",
            "application.commands.queries:ip_available", (
                P("address", required=True), P("scope", required=True))),
    local("ip expire", "local_read", "列出过期租约；--apply 加精确租约 ID 才释放", (
        P("apply", "boolean", default=False), P("lease_id"))),
    local("plan list", "local_read", "列出计划"),
    local("plan show", "local_read", "查看计划及不可变摘要", (P("plan_id", required=True, positional=True),)),
    local("audit list", "local_read", "分页查询脱敏审计事件，不连接远端", LIMIT + (
        P("after_id", "integer", default=0, minimum=0), P("snapshot_max_id", "integer", minimum=0))),
    local("audit export", "local_write", "导出脱敏 JSON 证据，拒绝覆盖已有文件", (
        P("file", required=True), P("limit", "integer", default=10000, minimum=1, maximum=10000),
        P("after_id", "integer", default=0, minimum=0), P("snapshot_max_id", "integer", minimum=0))),
    query("inventory list", "批量读取资产", LIMIT + (P("kind", default="vm", choices=("vm", "host", "cluster", "datastore")),)),
    Command("inventory export", "remote_read", "导出资产到新文件，不覆盖已有文件；json/csv，外部字段转义",
            "application.commands.queries:inventory_export", (
                P("file", required=True), P("kind", default="vm", choices=("vm", "host", "cluster", "datastore")),
                P("format", default="json", choices=("json", "csv")),
                P("limit", "integer", default=100, minimum=1, maximum=1000)), mcp=False),
    Command("events list", "remote_read", "按精确对象/时间/类型查询事件，不执行变更",
            "application.commands.queries:events_list", (
                P("vm_id"), P("host_id"), P("since"), P("event_type"),
                P("limit", "integer", default=100, minimum=1, maximum=1000))),
    Command("quota check", "remote_read", "变更前容量预检，只预检不预留；缺字段返回不可用",
            "application.commands.queries:quota_check", (
                P("cluster_id"), P("host_id"), P("datastore_id"),
                P("cpu", "integer", minimum=0), P("memory_gb", "integer", minimum=0),
                P("storage_gb", "integer", minimum=0))),
    query("vm list", "查看 VM 清单", LIMIT),
    query("vm inspect", "精确查看 VM", SELECTOR, ("id", "name")),
    query("template list", "仅查询模板", LIMIT),
    query("template inspect", "精确查询模板，排除普通 VM", SELECTOR, ("id", "name")),
    query("host info", "精确查看主机", SELECTOR, ("id", "name")),
    query("cluster list", "查看集群", LIMIT),
    query("cluster info", "精确查看集群", SELECTOR, ("id", "name")),
    query("datastore list", "查看数据存储", LIMIT),
    query("datastore inspect", "精确查看数据存储", SELECTOR, ("id", "name")),
    query("alarm list", "读取指定对象及后代的可见触发告警，不确认或重置", LIMIT + (
        P("entity_id", description="省略时查询根目录及后代；提供精确对象 ID 限定范围"),
        P("status", choices=("red", "yellow", "green", "gray")))),
)


SEARCH_OPTIONS = LIMIT + (P("datastore_id", required=True), P("path", default=""),
                         P("recursive", "boolean", default=False, description="显式包含子目录；limit 仅限制输出，不限制服务端搜索工作量"),
                         P("request_id"), P("wait", "boolean", default=True))
COMMANDS += (
    Command("datastore browse", "remote_read", "浏览目录；显式 recursive 才包含子目录", "application.commands.datastores:browse", SEARCH_OPTIONS, privileges=("Datastore.Browse",), asynchronous=True),
    Command("datastore scan", "remote_read", "发现 ISO/OVA/OVF，持久化搜索任务，不部署", "application.commands.datastores:scan", SEARCH_OPTIONS, privileges=("Datastore.Browse",), asynchronous=True),
    Command("datastore search-status", "remote_read", "核对原搜索任务，不重新搜索", "application.commands.datastores:search_status", (P("search_id", required=True, positional=True), P("wait", "boolean", default=False))),
    Command("datastore search-inspect", "local_read", "查看本地搜索记录及已保存结果", "application.commands.datastores:search_inspect", (P("search_id", required=True, positional=True),), mcp=False),
    Command("datastore search-list", "local_read", "列出当前 Profile 的搜索记录", "application.commands.datastores:search_list", LIMIT, mcp=False),
)
COMMANDS += (
    Command("cache status", "local_read", "离线查看指定 Profile 的资产缓存年龄、来源及服务端身份（TTL 300 秒）",
            "application.commands.cache:status", (P("kind", required=True, choices=("vm", "host", "cluster", "datastore")),), mcp=False),
    Command("cache refresh", "remote_read", "显式从远端只读刷新资产缓存；最多 1000 项且限制快照字节数（TTL 300 秒）",
            "application.commands.cache:refresh", (P("kind", required=True, choices=("vm", "host", "cluster", "datastore")),), mcp=False),
    Command("cache invalidate", "local_write", "仅删除指定 Profile 和资产类型的所有已记录服务端缓存",
            "application.commands.cache:invalidate", (P("kind", required=True, choices=("vm", "host", "cluster", "datastore")),), mcp=False),
)
VM_ID = (P("vm_id", required=True, description="精确 VM 对象 ID，如 vm-123"),)
PLACEMENT = (P("pool_id", required=True), P("datastore_id", required=True), P("host_id", required=True))
DISKS = P("disks", "array", description="显式 add/expand；capacity_gb 单位 GiB；add 使用负 device_key 和现有 SCSI 槽位", item_variants=(
    (P("operation", required=True, choices=("expand",)), P("device_key", "integer", required=True, minimum=0),
     P("capacity_gb", "integer", required=True, minimum=1)),
    (P("operation", required=True, choices=("add",)), P("device_key", "integer", required=True, maximum=-1),
     P("controller_key", "integer", required=True, minimum=0), P("unit_number", "integer", required=True, minimum=0, maximum=15),
     P("datastore_id", required=True), P("capacity_gb", "integer", required=True, minimum=1))))


def change(path, description, parameters=(), privileges=(), destructive=False):
    return Command(path, "remote_write", description, "application.commands.changes:" + path.replace(" ", "_").replace("-", "_"),
                   VM_ID + parameters + WRITE_OPTIONS, privileges=privileges, risk="destructive" if destructive else "change", asynchronous=True)


COMMANDS += (
    Command("alarm acknowledge", "remote_write", "确认精确实体上的告警，不代表故障恢复", "application.commands.changes:alarm_acknowledge",
            (P("entity_id", required=True), P("alarm_id", required=True)) + WRITE_OPTIONS, risk="change"),
    Command("alarm reset", "remote_write", "按受管对象类型+状态批量清除触发告警（6.7+，只能 vm/host，不能精确定位单个告警/实体）；预览绑定精确告警集合", "application.commands.changes:alarm_reset",
            (P("entity_type", required=True, choices=("vm", "host"),
               description="ClearTriggeredAlarms 的类型过滤仅有 VM/Host；不支持单个实体、告警 ID 或集群/数据存储"),
             P("statuses", "array", description="默认 red+yellow；只允许 red/yellow，去重")) + WRITE_OPTIONS,
            privileges=("Alarm.SetStatus",), risk="change"),
    query("vm snapshot-list", "读取带精确快照 ID 的树", VM_ID + LIMIT),
    query("vm tools-status", "读取 Tools 状态，缺失字段不编造", VM_ID),
    query("vm wait-tools", "限时等待 Tools 就绪，不修改 VM", VM_ID),
    change("vm power-on", "预览开机，不隐式创建 VM", privileges=("VirtualMachine.Interact.PowerOn",)),
    change("vm shutdown", "优雅关机，不回退强制关机", privileges=("VirtualMachine.Interact.PowerOff",)),
    change("vm power-off", "强制关机，可能丢失未保存数据", privileges=("VirtualMachine.Interact.PowerOff",)),
    change("vm reset", "硬重置 VM", privileges=("VirtualMachine.Interact.Reset",)),
    change("vm suspend", "挂起 VM", privileges=("VirtualMachine.Interact.Suspend",)),
    change("vm rename", "只修改 VM 名称", (P("new_name", required=True),), ("VirtualMachine.Config.Rename",)),
    change("vm reconfigure", "关机状态下修改 CPU/内存及显式磁盘列表；容量单位 GiB；磁盘不可补偿", (P("cpu", "integer", minimum=1), P("memory_gb", "integer", minimum=1), DISKS), ("VirtualMachine.Config.CPUCount", "VirtualMachine.Config.Memory", "VirtualMachine.Config.DiskExtend", "VirtualMachine.Config.AddNewDisk")),
    Command("vm delete", "remote_write",
            "受控销毁：先做全 vCenter 清单扫描证明本 vCenter 内无其他 VM/模板或快照引用其磁盘链；跨 vCenter/独立 ESXi 不可见，仍须显式 --allow-shared-datastore 担保并经 plan apply 双重确认，否则拒绝",
            "application.commands.changes:vm_delete",
            VM_ID + (P("allow_shared_datastore", "boolean", default=False,
                       description="操作者已确认该 VM 的共享数据存储未被本 vCenter 之外的其他 vCenter 或独立 ESXi 挂载引用；缺省不放行"),) + WRITE_OPTIONS,
            privileges=("VirtualMachine.Inventory.Delete",), risk="destructive", asynchronous=True),
    change("vm snapshot-create", "创建快照，不默认为内存快照", (P("snapshot_name", required=True), P("description"), P("memory", "boolean", default=False), P("quiesce", "boolean", default=False)), ("VirtualMachine.State.CreateSnapshot",)),
    change("vm snapshot-revert", "严格保护：无法排除外部链接磁盘依赖时拒绝恢复；当前不能执行", (P("snapshot_id", required=True),), ("VirtualMachine.State.RevertToSnapshot",), True),
    change("vm snapshot-delete", "严格保护：无法排除外部链接磁盘依赖时拒绝清理；当前不能执行", (P("snapshot_id", required=True),), ("VirtualMachine.State.RemoveSnapshot",), True),
    change("deploy mark-template", "只转换为模板，不重命名", privileges=("VirtualMachine.Provisioning.MarkAsTemplate",)),
    Command("template convert", "remote_write", "将精确模板转换为 VM，不改名不开机", "application.commands.changes:template_convert",
            VM_ID + (P("pool_id", required=True), P("host_id", required=True)) + WRITE_OPTIONS,
            privileges=("VirtualMachine.Provisioning.MarkAsVM", "Resource.AssignVMToPool"), risk="change"),
    change("deploy iso", "编辑已有光驱装载 ISO；先 browse/scan + search-status 完成搜索，search_id 创建时间须在300秒内", (
        P("cdrom_key", "integer", required=True, minimum=0), P("datastore_id", required=True),
        P("path", required=True), P("search_id", required=True)), ("VirtualMachine.Config.EditDevice", "VirtualMachine.Interact.SetCDMedia", "VirtualMachine.Interact.DeviceConnection", "Datastore.Browse")),
    change("deploy unmount-iso", "断开并清除已有光驱介质，不删除 ISO", (P("cdrom_key", "integer", required=True, minimum=0),),
           ("VirtualMachine.Config.EditDevice", "VirtualMachine.Interact.SetCDMedia", "VirtualMachine.Interact.DeviceConnection")),
    change("vm clone", "克隆为关机 VM，不隐式预留 IP 或改网", PLACEMENT + (P("folder_id", required=True), P("name", required=True)), ("VirtualMachine.Provisioning.Clone",)),
    change("deploy template", "从模板部署关机 VM", PLACEMENT + (P("folder_id", required=True), P("name", required=True)), ("VirtualMachine.Provisioning.DeployTemplate",)),
    Command("deploy clone-template", "remote_write",
            "对齐 vcenter-ops 克隆模版标准流程：从模板一次性克隆；可选改网/CPU/内存/磁盘扩容/静态 IP（给 IP 即开机 Linux 定制，不给则关机）；host_id 省略走集群 DRS",
            "application.commands.changes:deploy_clone_template", (
                P("vm_id", required=True, description="精确模板对象 ID，如 vm-123"),
                P("name", required=True, description="新 VM 名称，1–80 字符"),
                P("folder_id", required=True), P("pool_id", required=True),
                P("datastore_id", required=True), P("host_id", description="省略时由集群 DRS 调度"),
                P("network_id", description="省略则保留模板网卡；标准网络 network-N 或分布式端口组 dvportgroup-N"),
                P("cpu", "integer", minimum=1, description="克隆时改配 CPU 核数；省略保留模板"),
                P("memory_gb", "integer", minimum=1, description="克隆时改配内存 GiB；省略保留模板"),
                P("disk_gb", "integer", minimum=1, description="首盘目标容量 GiB，仅支持大于模板当前值的扩容"),
                P("ip_address", description="给定静态 IPv4 即开机并下发 Linux 定制；省略则克隆为关机 VM"),
                P("subnet_mask", default="255.255.255.0", description="静态 IP 子网掩码，默认 255.255.255.0"),
                P("gateway", description="静态 IP 默认网关；省略则不设网关"),
                P("guest_domain", default="local", description="Linux 定制域，默认 local")) + WRITE_OPTIONS,
            privileges=("VirtualMachine.Provisioning.DeployTemplate", "VirtualMachine.Inventory.CreateFromExisting",
                        "Resource.AssignVMToPool", "Datastore.AllocateSpace", "Network.Assign",
                        "VirtualMachine.Interact.PowerOn", "VirtualMachine.Provisioning.Customize"),
            risk="change", asynchronous=True, provider_kind="template_clone"),
    change("vm migrate", "省略 datastore_id 仅允许明确无磁盘且无 NVDIMM 的计算迁移；带磁盘时缺 PBM 策略证据而拒绝；指定存储也拒绝", (P("pool_id", required=True), P("host_id", required=True), P("datastore_id")), ("Resource.ColdMigrate",)),
    Command("plan apply", "orchestration", "确认并执行固定计划", "application.commands.changes:plan_apply",
            (P("plan_id", required=True, positional=True), P("confirm"), P("confirm_destruction"), P("wait", "boolean", default=True)), risk="change", mcp=False),
    Command("plan reconcile", "remote_read", "核对原任务，不重复提交", "application.commands.changes:plan_reconcile",
            (P("plan_id", required=True, positional=True), P("wait", "boolean", default=False))),
)


def workflow(path, category, description, parameters=()):
    return Command(path, category, description, "application.commands.plans:" + path.replace(" ", "_").replace("-", "_"), parameters)


COMMANDS += (
    workflow("plan create", "orchestration", "从声明式文件预览固定计划", (P("file", required=True), P("request_id"))),
    workflow("plan validate", "remote_read", "只核对前提，不执行", (P("plan_id", required=True, positional=True),)),
    workflow("plan archive", "local_write", "归档已结束计划，保留证据", (P("plan_id", required=True, positional=True),)),
    workflow("plan rollback", "orchestration", "预览可执行补偿，明确不能恢复的步骤", (P("plan_id", required=True, positional=True),)),
    workflow("task list", "local_read", "查询本地操作记录", LIMIT),
    workflow("task inspect", "local_read", "查看持久化操作与任务身份", (P("operation_id", required=True, positional=True),)),
    workflow("task reconcile", "remote_read", "只核对已提交任务", (P("operation_id", required=True, positional=True),)),
    workflow("task wait", "remote_read", "限时等待已提交任务，不重发", (P("operation_id", required=True, positional=True),)),
    Command("task cancel", "orchestration", "请求取消原任务，不将请求等同已取消", "application.commands.plans:task_cancel", (P("operation_id", required=True, positional=True), P("confirm")), risk="change", mcp=False),
) + tuple(workflow("batch " + verb, "orchestration", "只构建固定对象计划，不提交远端变更",
                   (P("vm_ids", "array", required=True, description='JSON 数组，例如 ["vm-1","vm-2"]'), P("request_id")))
          for verb in ("power-on", "power-off", "shutdown", "reset"))

COMMANDS += HOST_COMMANDS + CLUSTER_COMMANDS + CREATION_COMMANDS + SECRET_COMMANDS + HISTORY_PRESET_COMMANDS + POLICY_COMMANDS + GUEST_COMMANDS + LINKED_COMMANDS + OVF_COMMANDS


def lookup(path):
    for command in COMMANDS:
        if path in (command.path, command.operation_id):
            return command
    fail("command_unknown", "命令尚未实现或不存在", 2)


def capabilities():
    return {"release_stage": "execution_beta", "prd_complete": False,
            "commands": [c.describe() for c in COMMANDS],
            "vsphere": {v: "not_lab_verified" for v in ("6.5", "6.7", "7.0", "8.0")},
            "remaining_domains": ["linked_clone_acceptance", "typed_plan_output_references",
                                  "scans", "schedules", "notifications", "ttl", "mcp", "migration"],
            "beta_note": "OVA/OVF、Guest 输出/传输/定制、alarm reset 已注册并离线验收，实机未验收",
            "limitations": ["实机与跨平台安装尚未验收（新增 OVA/OVF、Guest、alarm reset 待真机矩阵）", "快照恢复后的依赖步骤尚不能自动推演", "补偿目前覆盖改名和可表示的 CPU/内存字段", "放置预检尚不构成完整兼容性试验", "alarm reset 只能按 VM/Host 类型+状态批量清除，不能精确定位单个告警或实体"]}
