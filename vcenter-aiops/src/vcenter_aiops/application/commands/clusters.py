"""Cluster commands enter the shared confirmed execution path."""
from .changes import preview


def cluster_remove_host(ctx, params):
    return preview(ctx, "cluster remove-host", params)


def cluster_create(ctx, params):
    return preview(ctx, "cluster create", params)


def cluster_configure(ctx, params):
    return preview(ctx, "cluster configure", params)


def cluster_delete(ctx, params):
    return preview(ctx, "cluster delete", params)
