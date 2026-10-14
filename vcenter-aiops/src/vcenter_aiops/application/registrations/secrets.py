from ...domain.contracts import Command, Parameter as P

NAME = (P("name", required=True, positional=True, description="全局精确名称：[A-Za-z0-9_-]{1,64}"),)
INPUT = (P("stdin", "boolean", default=False, description="显式从 stdin 读取非空 UTF-8 秘密，最多 4096 字节；仅移除一个结尾换行，否则使用隐藏终端输入"),)

COMMANDS = (
    Command("secret list", "local_read", "列出全局秘密的名称、修订号和 UTC 时间；拒绝 Profile 过滤",
            "application.commands.secrets:list_secrets", mcp=False),
    Command("secret set", "local_write", "创建全局秘密，不覆盖已有项；值最多 4096 UTF-8 字节",
            "application.commands.secrets:set_secret", NAME + INPUT, mcp=False),
    Command("secret rotate", "local_write", "替换精确秘密值并递增修订号；不是主密钥轮换，最多 4096 UTF-8 字节",
            "application.commands.secrets:rotate_secret", NAME + INPUT, mcp=False),
    Command("secret delete", "local_write", "删除全局精确名称的秘密",
            "application.commands.secrets:delete_secret", NAME, mcp=False),
)
