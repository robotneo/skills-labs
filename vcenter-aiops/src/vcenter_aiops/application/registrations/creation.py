"""Empty VM creation requires every placement and hardware input explicitly."""
from ...domain.contracts import Command, Parameter as P
from . import WRITE_OPTIONS

COMMANDS = (Command("vm create", "remote_write", "创建关机空白 VM；容量单位 GiB，不分配 IP",
    "application.commands.creation:vm_create",
    tuple(P(key, required=True) for key in ("name", "folder_id", "pool_id", "host_id", "datastore_id",
                                           "network_id", "guest_id", "hardware_version")) +
    tuple(P(key, "integer", required=True, minimum=1) for key in ("cpu", "memory_gb", "disk_gb")) + WRITE_OPTIONS,
    privileges=("VirtualMachine.Inventory.Create", "VirtualMachine.Config.AddNewDisk",
                "Resource.AssignVMToPool", "Datastore.AllocateSpace", "Network.Assign"),
    risk="change", asynchronous=True, provider_kind="creation"),)
