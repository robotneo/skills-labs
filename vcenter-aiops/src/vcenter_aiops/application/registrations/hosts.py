"""Host-maintenance command contracts."""
from ...domain.contracts import Command, Parameter as P
from . import WRITE_OPTIONS


HOST_ID = (P("host_id", required=True, description="精确 host-N 对象 ID，如 host-123"),)
TASK_TIMEOUT = (P("task_timeout", "integer", default=300, minimum=1, maximum=86400),)

COMMANDS = (
    Command(
        "host maintenance-enter",
        "remote_write",
        "显式预览 VM/DRS 影响后让精确主机进入维护模式",
        "application.commands.hosts:host_maintenance_enter",
        HOST_ID + TASK_TIMEOUT + (
            P("evacuate_powered_off_vms", "boolean", default=False),
            P("allow_drs_migration", "boolean", default=False),
        ) + WRITE_OPTIONS,
        privileges=("Host.Config.Maintenance",),
        risk="change",
        asynchronous=True,
        provider_kind="host",
    ),
    Command(
        "host maintenance-exit",
        "remote_write",
        "让精确主机退出维护模式，不创建额外撤离操作",
        "application.commands.hosts:host_maintenance_exit",
        HOST_ID + TASK_TIMEOUT + WRITE_OPTIONS,
        privileges=("Host.Config.Maintenance",),
        risk="change",
        asynchronous=True,
        provider_kind="host",
    ),
)
