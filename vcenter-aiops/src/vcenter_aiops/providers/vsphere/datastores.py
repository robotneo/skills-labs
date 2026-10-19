"""Metadata-only datastore searches with portable receipts and bounded observation."""
from datetime import datetime, timezone
import re
import time

from ...domain.models import OperationError, SubmissionRejected, fail
from .mor import existing

# Real vCenter DatastoreBrowser tasks are session-scoped managed objects whose
# _moId looks like ``session[52cbcdca-...]525c034d-...``; older/embedded builds
# may use the simple ``task-N`` form. Validate the managed-object-id shape
# conservatively (bounded length, no whitespace/quotes/path or shell
# metacharacters) instead of assuming one numeric form. Real identity binding is
# done separately via about.instanceUuid and task.info.key == recorded id.
_TASK_ID = re.compile(r"^(?:task-\d+|session\[[A-Za-z0-9._-]{1,128}\][A-Za-z0-9._-]{0,128})$")
_DATASTORE_ID = re.compile(r"^datastore-\d+$")


def valid_task_id(task_id):
    return isinstance(task_id, str) and bool(_TASK_ID.fullmatch(task_id))


class Datastores:
    def __init__(self, si, resolver=None):
        self.si = si
        self.resolver = resolver or self.resolve
        # ServiceContent (and about.instanceUuid) is constant for one session.
        # Cache lazily so a single browse issues one RetrieveProperties round
        # trip instead of one per prepare/observe call; pyVmomi does not cache it.
        self._content = None

    @property
    def content(self):
        if self._content is None:
            self._content = self.si.RetrieveContent()
        return self._content

    @property
    def server_uuid(self):
        return self.content.about.instanceUuid

    def resolve(self, object_id):
        from pyVmomi import vim
        return vim.Datastore(object_id, self.si._stub)

    def search(self, datastore_id, path="", limit=100, timeout=30, images_only=False):
        return self.observe(self.submit(self.prepare(datastore_id, path, limit, images_only)), timeout)

    def prepare(self, datastore_id, path="", limit=100, images_only=False, recursive=False):
        if not _DATASTORE_ID.fullmatch(datastore_id):
            fail("target_invalid", "需要精确 datastore-N 对象 ID", 2)
        if not isinstance(path, str) or path.startswith("/") or any(c in path for c in "[]\\%") or any(ord(c) < 32 for c in path) or any(p in (".", "..") for p in path.split("/")):
            fail("path_invalid", "只允许数据存储内的相对目录，不允许转义或路径穿越", 2)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            fail("query_invalid", "结果限制须为 1–1000", 2)
        ds = self.resolver(datastore_id)
        existing(lambda: ds.summary, datastore_id, "datastore_not_found",
                 "指定数据存储不存在或已被删除: " + datastore_id)
        if not ds.summary.accessible:
            fail("datastore_unavailable", "数据存储当前不可访问", 4)
        if any(c in ds.name for c in "[]\r\n"):
            fail("path_invalid", "无法安全表示此数据存储名称", 4)
        server_uuid = self.server_uuid
        if not server_uuid:
            fail("server_identity_missing", "无法绑定服务端身份", 4)
        return {"datastore_id": datastore_id, "datastore_name": ds.name, "path": path,
                "limit": limit, "images_only": images_only, "recursive": recursive, "server_uuid": server_uuid}

    def submit(self, scope):
        from pyVmomi import vim
        # M-3: narrow the prepare→submit TOCTOU re-check. The recorded scope was
        # already validated by prepare(); the input-derived fields
        # (path/limit/images_only/recursive) cannot drift, so re-confirm only the
        # remote liveness facts that can change underneath us — existence,
        # accessibility, datastore name (used to build datastorePath) and server
        # identity — instead of re-running the whole validation/prepare chain and
        # resolving the object twice.
        #
        # This whole block is read-only and runs before the single browse task is
        # started below, so any OperationError it raises proves no remote task was
        # launched: wrap it as SubmissionRejected (exit 4) so the application can
        # mark the search deterministically failed instead of "unknown". The write
        # method and its response handling stay outside the guarantee.
        try:
            ds = self.resolver(scope["datastore_id"])
            existing(lambda: ds.summary, scope["datastore_id"], "datastore_not_found",
                     "指定数据存储不存在或已被删除: " + scope["datastore_id"])
            if not ds.summary.accessible:
                fail("datastore_unavailable", "数据存储当前不可访问", 4)
            if ds.name != scope["datastore_name"]:
                fail("search_scope_changed", "数据存储名称已变化，禁止按旧路径提交搜索", 4)
            if self.server_uuid != scope["server_uuid"]:
                fail("search_scope_changed", "搜索范围或服务端身份已变化", 4)
        except OperationError as exc:
            raise SubmissionRejected(exc.code, str(exc), exc.exit_code) from exc
        full_path = "[" + scope["datastore_name"] + "]" + (" " + scope["path"] if scope["path"] else "")
        spec = vim.host.DatastoreBrowser.SearchSpec(details=vim.host.DatastoreBrowser.FileInfo.Details(fileSize=True, modification=True, fileType=True))
        method = ds.browser.SearchDatastoreSubFolders_Task if scope["recursive"] else ds.browser.SearchDatastore_Task
        task = method(datastorePath=full_path, searchSpec=spec)
        return {**scope, "task_id": task._moId}

    def task(self, task_id):
        from pyVmomi import vim
        return vim.Task(task_id, self.si._stub)

    def observe(self, scope, timeout=30):
        # M-3: this server-identity guard stays a *live* read, not the cached
        # self.server_uuid. Observe is the cross-session recovery entry point; if
        # the session was ever reconnected to a different vCenter, it must reject
        # a same-named task before reading it (fail-closed, same rule as M-2's
        # live identity reads). The M-3 caching win applies to prepare/submit,
        # where submit no longer re-runs the whole prepare chain.
        if self.si.RetrieveContent().about.instanceUuid != scope["server_uuid"]:
            fail("server_mismatch", "搜索任务属于其他 vCenter，禁止查询同名任务", 4)
        if not valid_task_id(scope["task_id"]):
            fail("task_identity_mismatch", "搜索任务身份无效", 4)
        task = self.task(scope["task_id"])
        deadline = time.monotonic() + timeout
        delay = 0.2
        while True:
            info = task.info
            if info.key != scope["task_id"]:
                fail("task_identity_mismatch", "返回任务与登记任务身份不匹配", 4)
            if str(info.state) == "success":
                break
            if str(info.state) == "error":
                fail("datastore_search_failed", "目录搜索失败；请检查路径与 Datastore.Browse 权限", 5)
            if str(info.state) not in ("queued", "running"):
                fail("datastore_search_unknown", "目录搜索任务状态未知", 6)
            if time.monotonic() >= deadline:
                return {**scope, "state": "running", "warnings": ["等待超时，原只读任务可能仍在服务端运行；未取消或重复提交"]}
            # M-3: exponential backoff (0.2s → … capped at 2s) instead of a
            # fixed 0.2s poll, matching the execution engine; never sleep past
            # the deadline.
            time.sleep(min(delay, max(0, deadline - time.monotonic())))
            delay = min(delay * 2, 2)
        if info.result is None:
            fail("datastore_search_unknown", "搜索成功但未返回结果，不能判定目录为空", 6)
        items, truncated = [], False
        folders = info.result if scope["recursive"] else [info.result]
        for folder in folders:
            for file in folder.file or []:
                if scope["images_only"] and not file.path.lower().endswith((".iso", ".ova", ".ovf")):
                    continue
                if len(items) == scope["limit"]:
                    truncated = True
                    break
                items.append({"name": file.path, "folder": folder.folderPath, "size_bytes": file.fileSize,
                              "modified_at": file.modification.isoformat() if file.modification else None,
                              "type": type(file).__name__})
            if truncated:
                break
        return {**scope, "state": "succeeded", "items": items, "truncated": truncated,
                "collected_at": datetime.now(timezone.utc).isoformat(), "untrusted_content": True,
                "warnings": ["镜像仅按文件扩展名发现，未验证可部署性"] if scope["images_only"] else []}
