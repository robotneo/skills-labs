from ...domain.contracts import Command, Parameter as P
from . import WRITE_OPTIONS


COMMANDS = (Command("deploy linked-clone", "remote_write",
    "从精确父 UUID/快照创建关机链接克隆；依赖长期保留，不能排除依赖时拒绝父磁盘清理；许可最终由服务端校验",
    "application.commands.linked:deploy_linked_clone",
    tuple(P(name, required=True) for name in ("vm_id", "parent_uuid", "snapshot_id", "name", "folder_id", "pool_id", "host_id", "datastore_id")) + WRITE_OPTIONS,
    privileges=("VirtualMachine.Provisioning.Clone", "VirtualMachine.Inventory.CreateFromExisting", "Resource.AssignVMToPool", "Datastore.AllocateSpace", "Datastore.Browse", "Network.Assign"),
    risk="change", asynchronous=True),)
