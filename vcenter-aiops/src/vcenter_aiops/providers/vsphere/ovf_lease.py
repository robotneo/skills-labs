"""HttpNfcLease driving state machine (no SDK import).

``importVapp`` returns an HttpNfcLease, not a Task. The hard, testable behaviour
is the lease progression: wait for ready, upload every importable device URL once,
call complete, then wait for done. Real HTTP PUT and SDK lease objects cross the
boundary in ``ovf_deploy.py``; here everything is injected so the full happy path,
error path and interrupted path run offline.

State names follow vim.HttpNfcLease.State (initializing/ready/transferring/done/
error). They are normalised from their string form so no SDK import is required.
"""
import time

from ...domain.models import OperationError, fail

# Bounded wait for vCenter to finalize the lease (verify/register) after all
# bytes have been pushed and HttpNfcLeaseComplete was called. This is a short
# server-side step, distinct from the (unbounded) byte transfer itself.
POST_COMPLETE_WAIT_SECONDS = 300


def state_name(value):
    text = str(value).rsplit(".", 1)[-1].lower()
    return text


def upload_targets(lease_info, files):
    """Pair descriptor files (order) with the lease's uploadable device URLs.

    Only device URLs flagged for upload are considered, in descriptor order. A
    count mismatch is rejected rather than partially or blindly uploaded.
    """
    device_urls = [u for u in getattr(lease_info, "deviceUrl", []) or []
                   if getattr(u, "upload", True)]
    if len(device_urls) != len(files):
        fail("ovf_lease_mismatch",
             f"导入设备数 {len(device_urls)} 与描述符磁盘数 {len(files)} 不一致，拒绝上传", 4)
    pairs = []
    for source_name, url in zip(files, device_urls):
        target = getattr(url, "url", None)
        if not target:
            fail("ovf_lease_url_missing", f"磁盘 {source_name} 缺少上传地址，拒绝导入", 4)
        pairs.append({"file": source_name, "url": target,
                      "thumbprint": getattr(url, "sslThumbprint", None),
                      "capacity": getattr(url, "capacity", None)})
    return pairs


def drive(lease, files, upload, *, sleep=time.sleep, clock=time.monotonic,
          deadline=None, init_delay=0.1, max_delay=2.0,
          post_complete_wait=POST_COMPLETE_WAIT_SECONDS):
    """Drive an HttpNfcLease to done, uploading each referenced file once.

    ``upload(target: dict, lease_info)`` performs the real HTTP PUT; it is the
    injected side effect. Returns the lease info on done. Raises OperationError
    on lease error or deadline (caller must then reconcile, never resubmit).

    Two bounded wait windows are kept separate. ``deadline`` bounds waiting for
    the lease to become ``ready`` (vCenter NFC preparation). The actual disk byte
    transfer runs synchronously inside the ready branch and is not charged to
    that window -- it is bounded by the HTTP layer's own per-connection timeout,
    so a slow but healthy large upload is never mistaken for a stuck lease. Once
    ``HttpNfcLeaseComplete`` is called, a distinct short ``post_complete_wait``
    window bounds vCenter finalization. No path waits forever.
    """
    uploaded = False
    delay = init_delay
    post_deadline = None
    while True:
        name = state_name(getattr(lease, "state", None))
        if name == "error":
            error = getattr(lease, "error", None)
            code = type(error).__name__ if error is not None else "HttpNfcLeaseError"
            fail("ovf_import_failed", f"NFC 导入租约进入错误态：{code}", 6)
        if name == "ready":
            if not uploaded:
                info = lease.info
                for target in upload_targets(info, files):
                    upload(target, info)
                # Signals the server all bytes are pushed; it then verifies/registers.
                lease.HttpNfcLeaseComplete()
                uploaded = True
                # Byte transfer just finished: the remaining wait is a separate
                # bounded server-side finalization window, not the init deadline.
                post_deadline = clock() + post_complete_wait
                delay = init_delay
        elif name == "done":
            return lease.info
        elif name in ("initializing", "transferring", "ready"):
            pass
        else:
            # Unknown lease state is uncertainty, never an auto-abort/resubmit.
            fail("ovf_lease_unknown", f"NFC 导入租约处于未知状态：{name}；请核对，不自动中止", 6)
        now = clock()
        active_deadline = post_deadline if uploaded else deadline
        if active_deadline is not None:
            if now >= active_deadline:
                fail("ovf_import_timeout", "NFC 导入在期限内未完成；请核对原租约，不重复提交", 6)
            sleep(min(delay, max(0.0, active_deadline - now)))
        else:
            sleep(delay)
        delay = min(delay * 2, max_delay)
