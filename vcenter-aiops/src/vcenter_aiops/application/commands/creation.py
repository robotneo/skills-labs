"""Creation enters the same confirmation and durable execution path."""
from .changes import preview


def vm_create(ctx, params):
    return preview(ctx, "vm create", params)
