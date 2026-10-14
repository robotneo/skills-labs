"""Guest SDK boundary: authentication, identity, launch and bounded observation."""
import os
import re

from ...domain.models import OperationError, SubmissionRejected, fail
from ...infrastructure.credentials import resolve_credential, validate_reference
from .guest_customize import validate_spec
from .guest_protocol import build_run, parse_markers, validate_path


def _validate_local_file(path):
    # A client-side spec path, not a Guest path: bounded encoding only.
    if not isinstance(path, str) or not path or len(path) > 4096 or any(ord(c) < 32 for c in path):
        fail("invalid_arguments", "spec_file 路径无效", 2)


def _load_spec(path):
    import json
    _validate_local_file(path)
    if not os.path.isfile(path):
        fail("guest_spec_invalid", "定制规格文件不存在", 2)
    if os.path.getsize(path) > 65536:
        fail("guest_spec_invalid", "定制规格文件超过 64 KiB", 2)
    text = open(path, encoding="utf-8")
    with text:
        content = text.read()
    try:
        import yaml
        data = yaml.safe_load(content)
    except ImportError:
        try:
            data = json.loads(content)
        except (ValueError, OSError):
            fail("guest_spec_invalid", "定制规格不是有效的 JSON（未安装 PyYAML）", 2)
    except Exception:
        fail("guest_spec_invalid", "定制规格不是有效的 YAML/JSON", 2)
    return validate_spec(data)


WARNINGS = ["需要 Guest 已安装且明确指定的 Python 3.10+；预览未执行探测，不会安装。",
            "显式包装器以 shell=False 传递 argv；exec 输出为 DEVNULL，exec-output 提供有界 stdout/stderr。",
            "Linux SDK 外层经 Guest shell 启动固定包装器；Windows argv 遵循 Python/CRT 规则。",
            "运行目录和标记永久保留，不自动清理；不抵抗同权限 Guest 用户或管理员伪造。",
            "claimed 仅证明本次运行已认领，不证明进程仍存活；超时结果未知，绝不重发。",
            "程序和参数会保存在固定计划中，请使用程序自身的安全凭据机制，不在 argv 放密码。"]

OUTPUT_WARNINGS = WARNINGS + [
    "stdout/stderr 最多各 64 KiB，超长部分在 Guest 侧截断；guest-output 只读不重执行。",
    "下载/上传单次上限 4 MiB；拒绝覆盖已有文件除非显式 overwrite。"]


class Guest:
    def __init__(self, si, resolver=None, tls=None):
        self.si = si
        self.content = si.RetrieveContent()
        self.resolver = resolver or self.object
        self._tls = tls or {}

    def object(self, kind, object_id):
        from pyVmomi import vim
        return vim.VirtualMachine(object_id, self.si._stub)

    @staticmethod
    def _safe_error(exc):
        if isinstance(exc, OperationError):
            return exc
        code = {"InvalidGuestLogin": "guest_authentication_failed", "GuestPermissionDenied": "guest_permission_denied",
                "NoPermission": "permission_denied", "GuestOperationsUnavailable": "guest_tools_unavailable",
                "GuestComponentsOutOfDate": "guest_tools_unavailable", "FileNotFound": "guest_result_missing"}.get(type(exc).__name__.split(".")[-1], "guest_sdk_failed")
        return OperationError(code, "Guest 调用未获得可验证结果；请核对身份、权限、Tools 或运行记录", 6)

    def _identity(self, params, execute=False):
        about = self.content.about
        if about.apiType != "VirtualCenter" or not re.match(r"^(6\.[57]|7\.0|8\.0)(\.|$)", about.apiVersion):
            fail("capability_unsupported", "Guest 仅支持目标范围内的 vCenter", 4)
        if not isinstance(about.instanceUuid, str) or not about.instanceUuid:
            fail("guest_identity_invalid", "无法确定 vCenter 身份", 4)
        if not re.fullmatch(r"vm-\d+", params["vm_id"]):
            fail("target_invalid", "Guest 要求精确 vm-N 对象 ID", 2)
        vm = self.resolver("vm", params["vm_id"])
        if vm._moId != params["vm_id"] or not vm.config or not vm.config.instanceUuid:
            fail("guest_identity_invalid", "无法确定 VM 唯一身份", 4)
        if vm.config.template or vm.runtime.connectionState != "connected" or vm.runtime.powerState != "poweredOn":
            fail("guest_unavailable", "Guest 要求已连接、已开机的普通 VM", 4)
        if vm.guest.guestFamily != params["os_family"] + "Guest":
            fail("guest_os_mismatch", "实际 Guest 系统与显式选择不匹配", 4)
        if vm.guest.toolsRunningStatus != "guestToolsRunning" or vm.guest.guestOperationsReady is not True:
            fail("guest_tools_unavailable", "Tools 或 Guest Operations 未就绪", 4)
        session = self.content.sessionManager.currentSession
        if not session:
            fail("session_missing", "服务端会话不可用", 3)
        privileges = ["VirtualMachine.GuestOperations.Query"]
        if execute:
            privileges.append("VirtualMachine.GuestOperations.Execute")
        granted = self.content.authorizationManager.HasPrivilegeOnEntity(entity=vm, sessionId=session.key, privId=privileges)
        if len(granted) != len(privileges) or any(x is not True for x in granted):
            fail("permission_denied", "账户缺少 Guest 操作权限", 4)
        return {"server_uuid": about.instanceUuid, "object_id": vm._moId, "instance_uuid": vm.config.instanceUuid}

    @staticmethod
    def _options(params):
        from ...application.registry import lookup
        params = lookup("vm guest-exec").validate(params)
        for key in ("request_id", "dry_run", "wait"):
            params.pop(key, None)
        validate_reference(params["credential_ref"])
        if len(params["guest_username"]) > 256 or any(ord(c) < 32 for c in params["guest_username"]):
            fail("invalid_arguments", "Guest 用户名无效", 2)
        if len(params["argv"]) > 128 or any(not isinstance(a, str) or "\x00" in a for a in params["argv"]):
            fail("invalid_arguments", "argv 须为最多 128 项且不含 NUL 的字符串数组", 2)
        if sum(len(a.encode("utf-8")) for a in params["argv"]) > 4096:
            fail("guest_arguments_too_large", "argv 超过 4096 字节", 2)
        for key in ("python_path", "program", "working_directory", "run_parent"):
            validate_path(params[key], params["os_family"])
        if params["os_family"] == "windows" and any(params[k].lower().endswith((".bat", ".cmd")) for k in ("python_path", "program")):
            fail("guest_program_unsupported", "Windows 要求直接可执行程序，不隐式启动批处理 shell", 2)
        if len(params["run_parent"]) > 60 and params["os_family"] == "windows":
            fail("guest_path_invalid", "Windows 私有父目录最多 60 字符，以限制完整标记路径长度", 2)
        return params

    @staticmethod
    def _customize_options(params):
        # A persisted binding already carries the loaded, validated spec. The
        # strict command schema does not declare customize_spec (the spec file
        # path is the user input), so rebinding must not push the enriched
        # object back through schema validation or re-read the local file.
        enriched = "customize_spec" in params
        raw = {k: v for k, v in params.items() if k != "customize_spec"} if enriched else dict(params)
        from ...application.registry import lookup
        raw = lookup("vm guest-customize").validate(raw)
        for key in ("request_id", "dry_run", "wait"):
            raw.pop(key, None)
        validate_reference(raw["credential_ref"])
        if len(raw["guest_username"]) > 256 or any(ord(c) < 32 for c in raw["guest_username"]):
            fail("invalid_arguments", "Guest 用户名无效", 2)
        for key in ("python_path", "run_parent"):
            validate_path(raw[key], raw["os_family"])
        _validate_local_file(raw["spec_file"])
        if raw["os_family"] == "windows" and raw["python_path"].lower().endswith((".bat", ".cmd")):
            fail("guest_program_unsupported", "Windows 要求直接可执行程序，不隐式启动批处理 shell", 2)
        if len(raw["run_parent"]) > 60 and raw["os_family"] == "windows":
            fail("guest_path_invalid", "Windows 私有父目录最多 60 字符", 2)
        if enriched:
            raw["customize_spec"] = validate_spec(params["customize_spec"])
        else:
            raw["customize_spec"] = _load_spec(raw["spec_file"])
        return raw

    def preflight(self, command, params, run_id=None):
        if command == "vm guest-customize":
            return self._preflight_customize(params, run_id)
        if command not in ("vm guest-exec", "vm guest-exec-output"):
            fail("capability_unsupported", "Guest Provider 不接受此命令", 4)
        try:
            params = self._options(params)
            capture = command == "vm guest-exec-output"
            identity = self._identity(params, True)
            return {**identity, "target": identity["server_uuid"] + ":" + identity["object_id"],
                    "before": {"os_family": params["os_family"], "tools": "guestToolsRunning"},
                    "risk": "change", "params": params,
                    "run": build_run(identity, params, run_id, capture=capture),
                    "warnings": OUTPUT_WARNINGS if capture else WARNINGS}
        except Exception as exc:
            raise self._safe_error(exc) from None

    def _preflight_customize(self, params, run_id=None):
        customize_warnings = WARNINGS + [
            "定制提交成功不代表来宾配置已完成（可能需等待 Tools、租约或重启）。",
            "仅按声明式规格执行，不隐式开机；Linux 按 name 选择网卡，MAC 解析需真机核对。"]
        try:
            params = self._customize_options(params)
            identity = self._identity(params, True)
            return {**identity, "target": identity["server_uuid"] + ":" + identity["object_id"],
                    "before": {"os_family": params["os_family"], "tools": "guestToolsRunning"},
                    "risk": "change", "params": params,
                    "run": build_run(identity, params, run_id, mode="customize"),
                    "warnings": customize_warnings}
        except Exception as exc:
            raise self._safe_error(exc) from None

    @staticmethod
    def matches(expected, actual):
        return {k: v for k, v in expected.items() if k != "run"} == {k: v for k, v in actual.items() if k != "run"}

    def _binding(self, binding):
        run = binding["run"]
        mode = run.get("mode", "exec")
        if mode == "customize":
            params = self._customize_options(binding["params"])
        elif mode in ("exec", "exec-output"):
            params = self._options(binding["params"])
        else:
            fail("guest_identity_invalid", "未知的 Guest 运行模式", 4)
        identity = self._identity(params)
        if any(binding.get(k) != v for k, v in identity.items()):
            fail("guest_identity_changed", "固定 vCenter 或 VM 身份已改变", 4)
        if run != build_run(identity, params, run["run_id"],
                            capture=run.get("capture_output", False), mode=mode):
            fail("guest_identity_invalid", "固定包装器描述不匹配，请人工核对版本与计划", 4)
        return params, run

    def _auth(self, params):
        from pyVmomi import vim
        return vim.vm.guest.NamePasswordAuthentication(username=params["guest_username"],
                    password=resolve_credential(params["credential_ref"]), interactiveSession=False)

    def submit(self, command, params, binding):
        from pyVmomi import vim
        if command not in ("vm guest-exec", "vm guest-exec-output", "vm guest-customize"):
            fail("capability_unsupported", "Guest Provider 不接受此命令", 4)
        try:
            actual = self.preflight(command, params, binding["run"]["run_id"])
            # provider_kind is injected by ProviderRouter, not produced by preflight.
            if actual != {k: v for k, v in binding.items() if k != "provider_kind"}:
                fail("plan_stale", "Guest 固定启动描述已变化，请重新预览", 4)
            auth = self._auth(actual["params"])
        except Exception as exc:
            safe = self._safe_error(exc)
            raise SubmissionRejected(safe.code, str(safe), safe.exit_code) from None
        run = binding["run"]
        kind = vim.vm.guest.ProcessManager.WindowsProgramSpec if params["os_family"] == "windows" else vim.vm.guest.ProcessManager.ProgramSpec
        spec = kind(programPath=run["program_path"], arguments=run["arguments"], workingDirectory=run["working_directory"])
        try:
            pid = self.content.guestOperationsManager.processManager.StartProgramInGuest(
                vm=self.object("vm", binding["object_id"]), auth=auth, spec=spec)
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
                fail("guest_receipt_invalid", "启动响应没有有效 PID，禁止重发", 6)
            return self._receipt(binding, int(pid))
        except Exception as exc:
            raise self._safe_error(exc) from None
        finally:
            auth.password = ""

    @staticmethod
    def _receipt(binding, pid=None):
        return {"kind": "guest_wrapper", "pid": pid, "run_id": binding["run"]["run_id"], "digest": binding["run"]["digest"]}

    def recover_receipt(self, command, params, binding):
        if command not in ("vm guest-exec", "vm guest-exec-output", "vm guest-customize"):
            fail("guest_identity_invalid", "原提交意图与 Guest 固定描述不匹配", 4)
        run_mode = binding["run"].get("mode", "exec")
        command_is_customize = command == "vm guest-customize"
        # The stored run mode must agree with the command being recovered.
        if (run_mode == "customize") != command_is_customize:
            fail("guest_identity_invalid", "原提交意图与 Guest 固定描述不匹配", 4)
        # _binding dispatches option validation by the stored run mode, which
        # also re-checks that params match the fixed plan.
        self._binding(binding)
        return self._receipt(binding)

    # --- Direct (non-plan) output / transfer operations -----------------

    def _context(self):
        from . import guest_http
        return guest_http.ssl_context(
            verify_tls=self._tls.get("verify_tls", True),
            ca_file=self._tls.get("ca_file"))

    def fetch_output(self, binding):
        """Read a completed run's bounded stdout/stderr using its trusted binding."""
        from . import guest_http, guest_transfer
        params, run = self._binding(binding)
        if not run.get("capture_output"):
            fail("guest_run_not_captured", "该运行未启用输出捕获（exec 为 DEVNULL）", 4)
        auth = self._auth(params)
        try:
            vm = self.object("vm", binding["object_id"])
            file_manager = self.content.guestOperationsManager.fileManager
            listing = file_manager.ListFilesInGuest(
                vm=vm, auth=auth, filePath=run["directory"], index=0, maxResults=8)
            context = self._context()
            sep = "\\" if params["os_family"] == "windows" else "/"
            base = run["directory"].rstrip("/\\")

            def fetch(name):
                info = file_manager.InitiateFileTransferFromGuest(
                    vm=vm, auth=auth, guestFilePath=base + sep + name)
                return guest_http.get_url(info.url, context=context,
                                          max_bytes=guest_transfer.MAX_TRANSFER_BYTES)

            parsed = guest_transfer.read_output(listing, run,
                                                params["os_family"], fetch)
            if parsed is None:
                return {"state": "running", "run_id": run["run_id"]}
            return {"state": "succeeded", "run_id": run["run_id"], **parsed}
        finally:
            auth.password = ""

    def download_file(self, vm_id, username, credential_ref, guest_path, family):
        from . import guest_http, guest_transfer
        self._check_transfer_identity(vm_id, username, credential_ref, family)
        params = {"vm_id": vm_id, "os_family": family,
                  "guest_username": username, "credential_ref": credential_ref}
        auth = self._auth(params)
        try:
            vm = self.object("vm", vm_id)
            file_manager = self.content.guestOperationsManager.fileManager

            def initiate(path):
                return file_manager.InitiateFileTransferFromGuest(
                    vm=vm, auth=auth, guestFilePath=path)

            def fetch(url, max_bytes=None):
                return guest_http.get_url(url, context=self._context(),
                                          max_bytes=max_bytes)

            result = guest_transfer.download(
                initiate, fetch, guest_path=guest_path, family=family)
            return {"state": "succeeded",
                    **{k: v for k, v in result.items() if k != "payload"},
                    "payload": result["payload"]}
        finally:
            auth.password = ""

    def upload_file(self, vm_id, username, credential_ref, guest_path, family,
                    payload, overwrite=False):
        from . import guest_http, guest_transfer
        self._check_transfer_identity(vm_id, username, credential_ref, family)
        params = {"vm_id": vm_id, "os_family": family,
                  "guest_username": username, "credential_ref": credential_ref}
        auth = self._auth(params)
        try:
            vm = self.object("vm", vm_id)
            file_manager = self.content.guestOperationsManager.fileManager

            def initiate(path, size, overwrite_flag):
                info = file_manager.InitiateFileTransferToGuest(
                    vm=vm, auth=auth, guestFilePath=path,
                    fileAttributes=self._file_attributes(family),
                    fileSize=size, overwrite=overwrite_flag)
                return info.url

            def put(url, body):
                guest_http.put_url(url, body, context=self._context())

            result = guest_transfer.upload(
                initiate, put, guest_path=guest_path, family=family,
                payload=payload, overwrite=overwrite)
            return {"state": "succeeded", **result}
        finally:
            auth.password = ""

    def _file_attributes(self, family):
        from pyVmomi import vim
        if family == "windows":
            return vim.vm.guest.FileManager.WindowsFileAttributes()
        return vim.vm.guest.FileManager.PosixFileAttributes()

    def _check_transfer_identity(self, vm_id, username, credential_ref, family):
        """Validate identity preconditions for a non-plan transfer command."""
        validate_reference(credential_ref)
        if not isinstance(username, str) or not username or len(username) > 256:
            fail("invalid_arguments", "Guest 用户名无效", 2)
        params = {"vm_id": vm_id, "os_family": family,
                  "guest_username": username, "credential_ref": credential_ref}
        self._identity(params, False)

    def observe(self, receipt, binding):
        auth = None
        try:
            params, run = self._binding(binding)
            pid = receipt.get("pid")
            if receipt != self._receipt(binding, pid) or (pid is not None and (type(pid) is not int or pid <= 0)):
                fail("guest_receipt_invalid", "Guest 回执身份不匹配", 6)
            auth = self._auth(params)
            files = self.content.guestOperationsManager.fileManager.ListFilesInGuest(
                vm=self.object("vm", binding["object_id"]), auth=auth, filePath=run["directory"], index=0, maxResults=8)
            code = parse_markers(files, run, params["os_family"])
            result = {"state": "running" if code is None else "success" if code == 0 else "error",
                      "phase": "completion_pending" if code is None else "completed", "liveness": "unverified",
                      "identity_basis": "guest-wrapper-v1", "run_id": run["run_id"], "digest": run["digest"],
                      "pid": pid, "exit_code": code}
            if code is not None and run.get("capture_output"):
                output = self._read_captured(binding["object_id"], auth, files, run, params)
                result.update(output)
            if code is not None and code != 0:
                result["error"] = {"code": "guest_program_failed", "message": "Guest 程序返回非零退出码", "retryable": False}
            return result
        except Exception as exc:
            safe = self._safe_error(exc)
            return {"state": "unknown", "error": {"code": safe.code, "message": str(safe), "retryable": False}}
        finally:
            if auth is not None:
                auth.password = ""

    def _read_captured(self, object_id, auth, listing, run, params):
        from . import guest_http, guest_transfer
        context = guest_http.ssl_context(
            verify_tls=self._tls.get("verify_tls", True),
            ca_file=self._tls.get("ca_file"))
        file_manager = self.content.guestOperationsManager.fileManager
        vm = self.object("vm", object_id)
        sep = "\\" if params["os_family"] == "windows" else "/"
        base = run["directory"].rstrip("/\\")

        def fetch(name):
            guest_path = base + sep + name
            info = file_manager.InitiateFileTransferFromGuest(
                vm=vm, auth=auth, guestFilePath=guest_path)
            return guest_http.get_url(info.url, context=context,
                                      max_bytes=guest_transfer.MAX_TRANSFER_BYTES)

        # Reuse the validated listing for markers; fetch() supplies raw b64 bytes.
        parsed = guest_transfer.read_output(listing, run, params["os_family"], fetch)
        return {"stdout": parsed["stdout"], "stderr": parsed["stderr"]}

    def verify(self, command, params, binding, observation):
        if command not in ("vm guest-exec", "vm guest-exec-output", "vm guest-customize"):
            return False
        basis_ok = (observation.get("identity_basis") == "guest-wrapper-v1" and
                    (observation.get("run_id"), observation.get("digest"),
                     observation.get("exit_code"), observation.get("phase")) ==
                    (binding["run"]["run_id"], binding["run"]["digest"], 0, "completed"))
        if not basis_ok:
            return False
        if command == "vm guest-exec-output":
            # Captured streams must both be present (possibly empty strings).
            if not isinstance(observation.get("stdout"), str) or not isinstance(observation.get("stderr"), str):
                return False
        # customize verification proves the fixed wrapper applied the spec and
        # exited 0; some guest changes (hostname/network) may still need reboot.
        return True

    def cancel(self, receipt, binding):
        fail("cancellation_unsupported", "Guest 包装器不支持可保证身份的取消；不会发送 Kill", 4)
