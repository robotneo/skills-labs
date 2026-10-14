"""Guest command contracts."""
from ...domain.contracts import Command, Parameter as P
from . import WRITE_OPTIONS


_EXEC_FIELDS = (
    P("vm_id", required=True), P("guest_username", required=True),
    P("credential_ref", required=True), P("os_family", required=True, choices=("linux", "windows")),
    P("python_path", required=True), P("program", required=True),
    P("argv", "array", default=[]), P("working_directory", required=True), P("run_parent", required=True),
)

COMMANDS = (
    Command("vm guest-exec", "remote_write", "预览显式 Python 包装器；输出丢弃，完成由独立运行标识核对",
            "application.commands.guest:guest_exec", _EXEC_FIELDS + WRITE_OPTIONS,
            privileges=("VirtualMachine.GuestOperations.Execute", "VirtualMachine.GuestOperations.Query"),
            risk="change", asynchronous=True, provider_kind="guest"),
    Command("vm guest-exec-output", "remote_write", "执行并在 Guest 侧有界捕获 stdout/stderr（各 ≤64KiB）；完成绑定本次 run-id，不凭 PID 判定",
            "application.commands.guest:guest_exec_output", _EXEC_FIELDS + WRITE_OPTIONS,
            privileges=("VirtualMachine.GuestOperations.Execute", "VirtualMachine.GuestOperations.Query"),
            risk="change", asynchronous=True, provider_kind="guest"),
    Command("vm guest-process-status", "remote_read", "只核对已有 Guest 操作的运行标识与原子结果；不重发",
            "application.commands.guest:guest_process_status", (
                P("operation_id", required=True, positional=True), P("wait", "boolean", default=False)),
            privileges=("VirtualMachine.GuestOperations.Query",), provider_kind="guest"),
    Command("vm guest-output", "remote_read", "凭可信 run-id 只读已有运行的有界输出，不重新执行；缺失/损坏/身份不符返回不确定",
            "application.commands.guest:guest_output", (
                P("run_id", required=True, positional=True), P("wait", "boolean", default=False)),
            privileges=("VirtualMachine.GuestOperations.Query",), provider_kind="guest"),
    Command("vm guest-download", "remote_read", "从 Guest 下载单个有界文件（≤4MiB）到本地新文件，拒绝覆盖与路径穿越",
            "application.commands.guest:guest_download", (
                P("vm_id", required=True), P("guest_username", required=True),
                P("credential_ref", required=True), P("os_family", required=True, choices=("linux", "windows")),
                P("guest_path", required=True), P("file", required=True, description="本地目标文件，已存在则拒绝")),
            privileges=("VirtualMachine.GuestOperations.Query",), provider_kind="guest"),
    Command("vm guest-upload", "remote_write", "上传本地文件（≤4MiB）到 Guest 精确路径；默认拒绝覆盖，显式 overwrite 才覆盖",
            "application.commands.guest:guest_upload", (
                P("vm_id", required=True), P("guest_username", required=True),
                P("credential_ref", required=True), P("os_family", required=True, choices=("linux", "windows")),
                P("file", required=True, description="本地源文件"), P("guest_path", required=True),
                P("overwrite", "boolean", default=False)),
            privileges=("VirtualMachine.GuestOperations.Execute",),
            risk="change", provider_kind="guest"),
    Command("vm guest-customize", "remote_write", "按声明式规格（hostname/IP/掩码/网关/DNS）经固定包装器对已开机 VM 来宾定制；不隐式开机，提交成功不等同来宾配置完成",
            "application.commands.guest:guest_customize", (
                P("vm_id", required=True), P("guest_username", required=True),
                P("credential_ref", required=True), P("os_family", required=True, choices=("linux", "windows")),
                P("python_path", required=True), P("spec_file", required=True),
                P("run_parent", required=True)) + WRITE_OPTIONS,
            privileges=("VirtualMachine.GuestOperations.Execute", "VirtualMachine.GuestOperations.Query"),
            risk="change", asynchronous=True, provider_kind="guest"),
)

