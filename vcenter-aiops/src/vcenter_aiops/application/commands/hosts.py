"""Host maintenance command handlers using the shared execution path."""
from .changes import preview


def host_maintenance_enter(ctx, params):
    return preview(ctx, "host maintenance-enter", params)


def host_maintenance_exit(ctx, params):
    return preview(ctx, "host maintenance-exit", params)
