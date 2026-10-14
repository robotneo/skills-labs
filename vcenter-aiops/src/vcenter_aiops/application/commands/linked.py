from .changes import preview


def deploy_linked_clone(ctx, params):
    return preview(ctx, "deploy linked-clone", params)
