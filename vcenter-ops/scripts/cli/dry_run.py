"""
Module: scripts.cli.dry_run

Declarative mapping used to build the ``params`` block of a dry-run
response. The historical ``handler.main`` had ~30 repetitive lines like
``if args.hostname: params["hostname"] = args.hostname``; this table
describes the same behaviour once and for all.

Each entry is a tuple of:

- ``attr``  – argparse ``dest`` name to read from ``args``.
- ``key``   – key inside the ``params`` dict (defaults to ``attr``).
- ``truthy_only`` – when ``True`` (default) the value is emitted only if
  it evaluates truthy; useful for booleans/strings.
- ``value_map`` – optional callable to normalise the value before
  emitting (e.g. rename ``memory`` -> ``memory_gb``).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional


class DryRunField(NamedTuple):
    attr: str
    key: Optional[str] = None
    truthy_only: bool = True
    value_map: Optional[Callable[[Any], Any]] = None


# The list below is the single source of truth for dry-run parameter
# projection. Ordering matches the historical output for stability.
DRY_RUN_FIELDS: List[DryRunField] = [
    DryRunField("hostname"),
    DryRunField("template"),
    DryRunField("dc"),
    DryRunField("cluster"),
    DryRunField("ds"),
    DryRunField("network"),
    DryRunField("host_node"),
    DryRunField("cpu"),
    DryRunField("memory", key="memory_gb"),
    DryRunField("disk", key="disk_gb"),
    DryRunField("ip"),
    DryRunField("mask"),
    DryRunField("gw"),
    DryRunField("state"),
    DryRunField("power_on"),
    DryRunField("snap_action"),
    DryRunField("snap_name"),
    DryRunField("cmd"),
    DryRunField("target_host"),
    DryRunField("plan_action"),
    DryRunField("plan_steps"),
    DryRunField("plan_desc"),
    DryRunField("ttl_action"),
    DryRunField("ttl_minutes"),
    DryRunField("ds_name"),
    DryRunField("ds_path"),
    DryRunField("ds_scan"),
]

# Actions that never touch vCenter and therefore have no dry-run mode.
DRY_RUN_SKIP_ACTIONS = frozenset({
    "history",
    "preset",
    "secret",
    "danger",
    "ip_pool",
    "audit_report",
})


def build_dry_run_params(args, fields: Iterable[DryRunField] = DRY_RUN_FIELDS) -> Dict[str, Any]:
    """Project ``args`` onto a dict following the ``DRY_RUN_FIELDS`` schema.

    Args:
        args: ``argparse.Namespace`` produced by :func:`cli.arguments.build_parser`.
        fields: Optional override of the field table (mainly for testing).

    Returns:
        A dictionary suitable for ``Response.dry_run(action, params=...)``.
    """
    params: Dict[str, Any] = {}
    for field in fields:
        value = getattr(args, field.attr, None)
        if field.truthy_only and not value:
            continue
        if field.value_map is not None:
            value = field.value_map(value)
        params[field.key or field.attr] = value
    return params
