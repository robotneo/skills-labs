"""NFC disk upload boundary using the Python standard library only.

Real NFC upload correctness (redirects to ESXi hosts, cookie propagation, cert
thumbprints) is verified against a live vCenter, never claimed from offline tests.
This module is intentionally small and dependency-free so it can be replaced or
wrapped without touching the lease state machine.
"""
import http.client
import os
import ssl
import urllib.parse
from contextlib import closing

# NFC/Guest targets are vCenter-issued URLs but the lease can answer with 3xx
# redirects. An attacker-controlled (or compromised) endpoint must not be able to
# downgrade the channel to plaintext or pivot the payload/credentials at another
# host, so every hop is validated. TransferError subforms ConnectionError so the
# write-path callers, which let post-submit network failures surface as
# uncertainty (exit 6), keep their existing handling while gaining a stable code.
MAX_REDIRECTS = 4


class TransferError(ConnectionError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _host_of(url):
    # urlsplit().hostname strips credentials/userinfo and lowercases, so a
    # crafted "https://vcenter@evil/" target cannot spoof the allow-set match.
    host = urllib.parse.urlsplit(url).hostname
    if not host:
        raise TransferError("transfer_url_invalid", "传输 URL 缺少主机名")
    return host.lower()


def enforce_target(url, allowed_hosts, allow_plain_http=False, redirect=False):
    """Validate scheme and host of one transfer hop. Fail closed.

    https is always required; plain http needs an explicit per-call opt-in. The
    host must belong to ``allowed_hosts`` (already lower-cased). ``redirect``
    only selects a precise error code for a hop reached via a 3xx response.
    """
    parts = urllib.parse.urlsplit(url)
    scheme_code = "redirect_scheme_denied" if redirect else "transfer_scheme_denied"
    if parts.scheme not in ("http", "https"):
        raise TransferError(scheme_code, f"不支持的传输协议: {parts.scheme or '空'}")
    if parts.scheme == "http" and not allow_plain_http:
        raise TransferError(scheme_code, "拒绝明文 HTTP 传输，请使用 HTTPS")
    host = _host_of(url)
    if allowed_hosts is not None and host not in allowed_hosts:
        raise TransferError("redirect_host_denied",
                            "重定向目标主机不在 vCenter/ESXi 允许集合内: " + host)
    return host


def ssl_context(verify_tls=True, ca_file=None):
    if not verify_tls:
        context = ssl._create_unverified_context()
    elif ca_file:
        context = ssl.create_default_context(cafile=ca_file)
    else:
        context = ssl.create_default_context()
    return context


def put_file(url, source_path, headers, context=None, chunk=1024 * 1024,
             allowed_hosts=None, allow_plain_http=False):
    """PUT a local file to an NFC device URL, following up to 4 redirects.

    Every hop must stay on https unless the caller explicitly opts into plain
    http, and every host must belong to the allow-set. When ``allowed_hosts`` is
    omitted it is pinned to the first URL host (NFC normally redirects the
    vCenter host to a specific ESXi host, which the caller may pre-authorize).
    Redirects switch the Host header but keep the session Cookie (NFC targets the
    ESXi host which still accepts the vCenter session ticket for import).
    """
    current = url
    if allowed_hosts is None:
        allow = {_host_of(current)}
    else:
        allow = {h.lower() for h in allowed_hosts}
    enforce_target(current, allow, allow_plain_http=allow_plain_http)
    remaining = MAX_REDIRECTS
    while True:
        parts = urllib.parse.urlsplit(current)
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(
                parts.hostname, parts.port or 443, context=context, timeout=60)
        else:
            connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=60)
        body_headers = dict(headers)
        body_headers["Content-Length"] = str(os.path.getsize(source_path))
        body_headers["Content-Type"] = "application/x-vnd.vmware-streamVmdk"
        # Release the socket on every path (redirect/error/success); each hop is
        # a fresh one-shot connection.
        with open(source_path, "rb") as stream, closing(connection):
            connection.request("PUT", parts.path + (("?" + parts.query) if parts.query else ""),
                               body=_reader(stream, chunk), headers=body_headers)
            response = connection.getresponse()
            status = response.status
            if status in (301, 302, 303, 307, 308) and response.getheader("Location"):
                if remaining == 0:
                    raise TransferError("transfer_redirect_loop",
                                        "NFC 上传重定向次数过多")
                remaining -= 1
                current = urllib.parse.urljoin(current, response.getheader("Location"))
                # Validate the next hop BEFORE connecting: no downgrade, no
                # protocol switch, no pivot to a host outside the allow-set.
                enforce_target(current, allow,
                               allow_plain_http=allow_plain_http, redirect=True)
                continue
            if status not in (200, 201, 204):
                raise TransferError("transfer_rejected",
                                    f"NFC 上传被拒绝：HTTP {status}")
            return status


def _reader(stream, chunk):
    while True:
        block = stream.read(chunk)
        if not block:
            break
        yield block
