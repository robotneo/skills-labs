"""Module: scripts.cli.arguments -- argparse builder for handler.py.

Grouped helper functions register the argparse flags used by handler.py.
Every kebab-case flag also registers its historical snake-case alias so
existing external scripts keep working after the refactor.
"""

from __future__ import annotations

import argparse
from typing import Iterable, Optional, Sequence

DEFAULT_ACTION_CHOICES: Sequence[str] = (
    "list_all", "get_vm", "clone_vm", "delete_vm", "power_vm",
    "snapshot", "reconfigure", "guest_exec", "migrate", "plan", "ttl",
    "datastore", "template", "batch", "events", "quota", "export",
    "history", "preset", "ip_pool", "audit_report", "secret", "danger",
)


def _resolve_action_choices(choices):
    return DEFAULT_ACTION_CHOICES if choices is None else tuple(choices)


def _add_connection_args(parser):
    group = parser.add_argument_group("connection")
    group.add_argument("--host", help="vCenter host (defaults to config.yaml)")
    group.add_argument("--user", help="username (defaults to config.yaml)")
    group.add_argument("--pwd", help="password (defaults to config.yaml)")
    group.add_argument("--port", type=int, help="port (defaults to config.yaml)")


def _add_action_arg(parser, choices):
    parser.add_argument(
        "--action",
        choices=list(_resolve_action_choices(choices)),
        help="action to run (optional with --audit-query)",
    )


def _add_core_business_args(parser):
    group = parser.add_argument_group("core")
    group.add_argument("--hostname", help="VM name")
    group.add_argument("--template", help="template name for clone")
    group.add_argument("--dc", help="datacenter name")
    group.add_argument("--cluster", help="cluster name")
    group.add_argument("--ds", help="datastore name")
    group.add_argument("--network", help="target network / VLAN name")


def _add_hardware_args(parser):
    group = parser.add_argument_group("hardware")
    group.add_argument("--host-node", "--host_node", dest="host_node",
                       help="physical host node name")
    group.add_argument("--cpu", type=int, help="CPU core count")
    group.add_argument("--memory", type=int, help="memory size (GB)")
    group.add_argument("--disk", type=int, help="primary disk size (GB)")


def _add_network_args(parser):
    group = parser.add_argument_group("network")
    group.add_argument("--ip", help="static IP")
    group.add_argument("--mask", help="subnet mask")
    group.add_argument("--gw", help="default gateway")


def _add_power_and_snapshot_args(parser):
    group = parser.add_argument_group("power/snapshot")
    group.add_argument("--state", choices=["on", "off", "reset"],
                       help="power state")
    group.add_argument("--power-on", "--power_on", dest="power_on",
                       action="store_true", help="power on after operation")
    group.add_argument("--snap-action", "--snap_action", dest="snap_action",
                       choices=["create", "list", "revert", "delete"],
                       help="snapshot sub-action")
    group.add_argument("--snap-name", "--snap_name", dest="snap_name",
                       help="snapshot name")


def _add_execution_mode_args(parser):
    group = parser.add_argument_group("execution mode")
    group.add_argument("--dry-run", action="store_true", dest="dry_run",
                       help="dry-run: print planned action without executing")
    group.add_argument("--audit-query", action="store_true", dest="audit_query",
                       help="query audit log (with --action / --hostname)")


def _add_guest_and_migrate_args(parser):
    group = parser.add_argument_group("guest/migrate")
    group.add_argument("--cmd", help="command to run inside guest OS")
    group.add_argument("--guest-user", dest="guest_user", default="root",
                       help="guest OS user (default root)")
    group.add_argument("--guest-pwd", dest="guest_pwd", default="",
                       help="guest OS password")
    group.add_argument("--target-host", "--target_host", dest="target_host",
                       help="vMotion target host name / IP")


def _add_plan_args(parser):
    group = parser.add_argument_group("plan")
    group.add_argument("--plan-action", "--plan_action", dest="plan_action",
                       choices=["create", "execute", "rollback", "list", "delete"],
                       help="plan sub-action")
    group.add_argument("--plan-id", "--plan_id", dest="plan_id", help="plan id")
    group.add_argument("--plan-steps", "--plan_steps", dest="plan_steps",
                       help="plan steps (JSON list)")
    group.add_argument("--plan-desc", "--plan_desc", dest="plan_desc",
                       help="plan description")


def _add_ttl_args(parser):
    group = parser.add_argument_group("ttl")
    group.add_argument("--ttl-action", "--ttl_action", dest="ttl_action",
                       choices=["set", "cancel", "list", "cleanup"],
                       help="TTL sub-action")
    group.add_argument("--ttl-minutes", "--ttl_minutes", dest="ttl_minutes",
                       type=int, help="TTL minutes")
    group.add_argument("--creator", default="agent", help="TTL creator")


def _add_datastore_and_template_args(parser):
    group = parser.add_argument_group("datastore/template")
    group.add_argument("--ds-name", "--ds_name", dest="ds_name",
                       help="datastore name")
    group.add_argument("--ds-path", "--ds_path", dest="ds_path", default="",
                       help="datastore sub path")
    group.add_argument("--ds-scan", "--ds_scan", dest="ds_scan",
                       action="store_true",
                       help="scan every datastore for images")
    group.add_argument("--tpl-action", "--tpl_action", dest="tpl_action",
                       choices=["list", "register", "convert"],
                       help="template sub-action")
    group.add_argument("--tpl-name", "--tpl_name", dest="tpl_name",
                       help="template name (register)")


def _add_batch_args(parser):
    group = parser.add_argument_group("batch")
    group.add_argument("--batch-action", "--batch_action", dest="batch_action",
                       choices=["power"], help="batch sub-action")
    group.add_argument("--pattern", help="VM name glob pattern")


def _add_events_and_quota_args(parser):
    group = parser.add_argument_group("events/quota")
    group.add_argument("--minutes", type=int, help="event window in minutes")
    group.add_argument("--event-category", "--event_category",
                       dest="event_category",
                       choices=["power", "create_delete", "migration",
                                "snapshot", "alarm"],
                       help="event category filter")
    group.add_argument("--cpu-threshold", "--cpu_threshold",
                       dest="cpu_threshold", type=float,
                       help="CPU utilisation warn threshold (default 0.85)")
    group.add_argument("--mem-threshold", "--mem_threshold",
                       dest="mem_threshold", type=float,
                       help="memory utilisation warn threshold (default 0.85)")
    group.add_argument("--disk-threshold", "--disk_threshold",
                       dest="disk_threshold", type=float,
                       help="disk utilisation warn threshold (default 0.9)")


def _add_export_args(parser):
    group = parser.add_argument_group("export")
    group.add_argument("--export-format", "--export_format",
                       dest="export_format",
                       choices=["json", "csv", "markdown", "html"],
                       help="export format")
    group.add_argument("--output", help="output file path")
    group.add_argument("--top", type=int, default=50,
                       help="max results returned")


def _add_preset_and_history_args(parser):
    group = parser.add_argument_group("preset/history")
    group.add_argument("--preset", help="preset name (CLI values override)")
    group.add_argument("--from-last", action="store_true", dest="from_last",
                       help="reuse most recent clone parameters")
    group.add_argument("--from-vm", dest="from_vm",
                       help="reuse clone parameters of the given VM")
    group.add_argument("--no-wait-tools", action="store_true",
                       dest="no_wait_tools",
                       help="skip waiting for VMware Tools after clone")
    group.add_argument("--tools-timeout", type=int, dest="tools_timeout",
                       default=300,
                       help="Tools wait timeout seconds (default 300)")
    group.add_argument("--preset-action", dest="preset_action",
                       choices=["list", "save", "save-from-last", "delete", "show"],
                       help="preset sub-action")
    group.add_argument("--preset-name", dest="preset_name", help="preset name")
    group.add_argument("--preset-desc", dest="preset_desc", default="",
                       help="preset description")
    group.add_argument("--preset-overwrite", action="store_true",
                       dest="preset_overwrite", help="overwrite existing preset")


def _add_ip_pool_args(parser):
    group = parser.add_argument_group("ip-pool")
    group.add_argument("--ip-action", dest="ip_action",
                       choices=["available", "allocate", "release",
                                "reservations", "cleanup"],
                       help="IP pool sub-action")
    group.add_argument("--ip-spec", dest="ip_spec", help="IP pool declaration")
    group.add_argument("--ip-target", dest="ip_target",
                       help="IP address to release")
    group.add_argument("--count", type=int, help="IP allocate batch size")
    group.add_argument("--name-prefix", dest="name_prefix",
                       help="VM name prefix for IP reservation")


def _add_audit_report_args(parser):
    group = parser.add_argument_group("audit-report")
    group.add_argument("--report-days", type=int, dest="report_days",
                       default=7, help="audit report window in days")


def _add_security_args(parser):
    group = parser.add_argument_group("security")
    group.add_argument("--actor", default="agent", dest="acting_user",
                       help="current operator (audit / danger confirm)")
    group.add_argument("--confirmed", action="store_true",
                       help="second-confirmation flag for danger actions")
    group.add_argument("--secret-action", dest="secret_action",
                       choices=["list", "set", "get", "delete", "migrate", "rotate"],
                       help="secret sub-action")
    group.add_argument("--secret-key", dest="secret_key")
    group.add_argument("--secret-value", dest="secret_value")
    group.add_argument("--secret-desc", dest="secret_desc", default="")
    group.add_argument("--danger-action", dest="danger_action",
                       choices=["scan", "confirm", "patterns", "config"],
                       help="danger sub-action")
    group.add_argument("--danger-target", dest="danger_target")
    group.add_argument("--danger-op", dest="danger_op", default="delete_vm")


def build_parser(action_choices=None):
    """Return a fully-populated ``argparse.ArgumentParser`` for handler.py."""
    parser = argparse.ArgumentParser(description="vCenter Ops Handler")
    _add_connection_args(parser)
    _add_action_arg(parser, action_choices)
    _add_core_business_args(parser)
    _add_hardware_args(parser)
    _add_network_args(parser)
    _add_power_and_snapshot_args(parser)
    _add_execution_mode_args(parser)
    _add_guest_and_migrate_args(parser)
    _add_plan_args(parser)
    _add_ttl_args(parser)
    _add_datastore_and_template_args(parser)
    _add_batch_args(parser)
    _add_events_and_quota_args(parser)
    _add_export_args(parser)
    _add_preset_and_history_args(parser)
    _add_ip_pool_args(parser)
    _add_audit_report_args(parser)
    _add_security_args(parser)
    return parser
