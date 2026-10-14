from ...domain.contracts import Command, Parameter as P

NAME = (P("name", required=True, positional=True, description="Profile 内精确预设名"),)
PAGE = (P("limit", "integer", default=100, minimum=1, maximum=1000),)
PARAMS = (P("params", "object", required=True, description="当前命令完整 JSON 参数；不含确认、请求 ID、绑定或秘密"),)

COMMANDS = (
    Command("history list", "local_read", "分页查看本地计划历史；无 --profile 时明确查询全局",
            "application.commands.history_presets:history_list", PAGE +
            (P("after_id", "integer", default=0, minimum=0), P("snapshot_max_id", "integer", minimum=0)), mcp=False),
    Command("history show", "local_read", "精确查看计划与操作状态；不输出确认值、绑定或回执",
            "application.commands.history_presets:history_show", (P("plan_id", required=True, positional=True),), mcp=False),
    Command("preset list", "local_read", "分页列出指定 Profile 的预设；须 --profile",
            "application.commands.history_presets:preset_list", PAGE + (P("after_name"),), mcp=False),
    Command("preset show", "local_read", "精确查看并重新校验指定 Profile 的预设；须 --profile",
            "application.commands.history_presets:preset_show", NAME, mcp=False),
    Command("preset save", "local_write", "保存已注册远端原子命令的声明式参数，不预览或部署；须 --profile",
            "application.commands.history_presets:preset_save", NAME + (P("command_path", required=True),) + PARAMS, mcp=False),
    Command("preset delete", "local_write", "删除指定 Profile 内精确名称的预设；须 --profile",
            "application.commands.history_presets:preset_delete", NAME, mcp=False),
    Command("preset from-history", "local_write", "选取同 Profile 历史计划中的一个步骤，新建预设；不复用确认或操作",
            "application.commands.history_presets:preset_from_history", NAME +
            (P("plan_id", required=True), P("position", "integer", required=True, minimum=0)), mcp=False),
    Command("preset from-vm", "local_write", "只读来源 VM，保存目标 VM 的 CPU/整 GiB 内存配置预设；非部署/克隆模板；遗漏磁盘、网卡、控制器、存储及 UUID",
            "application.commands.history_presets:preset_from_vm", NAME +
            (P("source_vm_id", required=True, description="精确读取来源 vm-N"),
             P("target_vm_id", required=True, description="将来配置的目标 vm-N，必须显式提供")), mcp=False),
)
