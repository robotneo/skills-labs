from ...domain.contracts import Command, Parameter as P
from . import WRITE_OPTIONS


NETWORK_MAPPING = P("network_mapping", "object", required=True,
    description='描述符网络名到精确网络 ID 的映射，例如 {"VM Network":"network-12"}；目标须为 network-N 或 dvportgroup-N')


COMMANDS = (
    Command("deploy ova", "remote_write",
        "从本地单文件 OVA 导入关机 VM/ vApp：先安全解包（拒绝路径穿越）与描述符/网络/磁盘校验，再 OvfManager + NFC 上传；默认不开机、不隐式定制；中断须核对不重发",
        "application.commands.ovf:deploy_ova",
        (P("source", required=True, positional=True, description="本地 .ova 文件路径"),
         P("work_dir", required=True, description="解包工作目录；在其中创建 unpacked/"),
         P("name", required=True),
         P("resource_pool_id", required=True), P("host_id", required=True),
         P("folder_id", required=True), P("datastore_id", required=True),
         NETWORK_MAPPING) + WRITE_OPTIONS,
        privileges=("VApp.Import", "Datastore.AllocateSpace", "Datastore.Browse",
                    "Network.Assign", "Resource.AssignVMToPool"),
        risk="change", asynchronous=True, provider_kind="ovf"),
    Command("deploy ovf", "remote_write",
        "从本地 OVF 目录（descriptor.ovf + 引用磁盘）导入关机 VM/ vApp：校验映射后 OvfManager + NFC 上传；默认不开机、不隐式定制；中断须核对不重发",
        "application.commands.ovf:deploy_ovf",
        (P("source", required=True, positional=True, description="含 descriptor.ovf 的本地目录"),
         P("work_dir", required=True),
         P("name", required=True),
         P("resource_pool_id", required=True), P("host_id", required=True),
         P("folder_id", required=True), P("datastore_id", required=True),
         NETWORK_MAPPING) + WRITE_OPTIONS,
        privileges=("VApp.Import", "Datastore.AllocateSpace", "Datastore.Browse",
                    "Network.Assign", "Resource.AssignVMToPool"),
        risk="change", asynchronous=True, provider_kind="ovf"),
)
