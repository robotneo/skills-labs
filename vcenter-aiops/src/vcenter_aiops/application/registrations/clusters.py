"""Strict cluster lifecycle command contracts."""
from ...domain.contracts import Command, Parameter as P
from . import WRITE_OPTIONS

CONFIG = (P("ha_enabled", "boolean"), P("drs_enabled", "boolean"),
          P("drs_automation", choices=("manual", "partiallyAutomated", "fullyAutomated")),
          P("drs_vmotion_rate", "integer", minimum=1, maximum=5))
COMMANDS = (
    Command("cluster remove-host", "remote_write", "保留在 vCenter，转为独立主机；需要二次确认", "application.commands.clusters:cluster_remove_host",
            (P("cluster_id", required=True), P("host_id", required=True), P("folder_id", required=True)) + WRITE_OPTIONS,
            privileges=("Host.Inventory.EditCluster", "Host.Inventory.MoveHost", "Host.Inventory.AddStandaloneHost"),
            risk="destructive", asynchronous=True, provider_kind="membership"),
    Command("cluster create", "remote_write", "在精确 host folder 创建集群", "application.commands.clusters:cluster_create",
            (P("folder_id", required=True), P("name", required=True), P("ha_enabled", "boolean", default=False),
             P("drs_automation", default="manual", choices=("manual", "partiallyAutomated", "fullyAutomated"))) + WRITE_OPTIONS,
            privileges=("Host.Inventory.CreateCluster",), risk="change", provider_kind="cluster"),
    Command("cluster configure", "remote_write", "只增量修改明确选择的 HA/DRS 字段", "application.commands.clusters:cluster_configure",
            (P("cluster_id", required=True),) + CONFIG + WRITE_OPTIONS,
            privileges=("Host.Inventory.EditCluster",), risk="change", asynchronous=True, provider_kind="cluster"),
    Command("cluster delete", "remote_write", "二次确认后删除精确空集群", "application.commands.clusters:cluster_delete",
            (P("cluster_id", required=True),) + WRITE_OPTIONS,
            privileges=("Host.Inventory.DeleteCluster",), risk="destructive", asynchronous=True, provider_kind="cluster"),
)
