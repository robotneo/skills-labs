from ...domain.contracts import Command, Parameter as P

COMMANDS = (
    Command("policy inspect", "local_read", "查看静态 schema、风险与声明权限；不查询远端权限或授权执行",
            "application.commands.policy:inspect", (P("command_path", required=True, positional=True),), mcp=False),
    Command("policy check", "local_read", "仅检查静态命令参数；不签发确认、不消耗确认、不提交任务",
            "application.commands.policy:check", (P("command_path", required=True, positional=True),
                                                  P("params", "object", required=True)), mcp=False),
)
