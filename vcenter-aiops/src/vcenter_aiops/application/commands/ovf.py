from .changes import preview


def deploy_ova(ctx, params):
    return preview(ctx, "deploy ova", params)


def deploy_ovf(ctx, params):
    return preview(ctx, "deploy ovf", params)
