"""Guest file transfer boundary using the Python standard library only.

vCenter returns a one-time HTTPS URL (with an auth ticket in the query string)
for InitiateFileTransferFromGuest / InitiateFileTransferToGuest. The real URL
format, certificate and ticket behaviour are verified against a live vCenter and
never claimed from offline tests. This module only performs the HTTP fetch/put
and is deliberately dependency-free.
"""
import http.client
import urllib.parse
from contextlib import closing

from .ovf_http import TransferError, enforce_target, ssl_context

# ssl_context is defined in ovf_http and intentionally re-exported here: guest.py
# resolves it as ``guest_http.ssl_context`` right next to get_url/put_url. Listing
# it in __all__ marks the import as a deliberate public re-export, not dead code.
__all__ = ("get_url", "put_url", "ssl_context", "TransferError")


def get_url(url, context=None, chunk=1024 * 1024, max_bytes=None,
            allow_plain_http=False):
    # vCenter issues a one-time https URL; reject plaintext unless the caller
    # explicitly opts in (Guest one-time URLs never follow redirects).
    enforce_target(url, None, allow_plain_http=allow_plain_http)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(
            parts.hostname, parts.port or 443, context=context, timeout=60)
    else:
        connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=60)
    path = parts.path + (("?" + parts.query) if parts.query else "")
    # Always release the underlying socket, including the non-200 and
    # over-limit raise paths (a one-shot URL, so Connection: close).
    with closing(connection):
        connection.request("GET", path, headers={"Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            raise ConnectionError(f"Guest 文件下载被拒绝：HTTP {response.status}")
        collected = bytearray()
        while True:
            block = response.read(chunk)
            if not block:
                break
            collected.extend(block)
            if max_bytes is not None and len(collected) > max_bytes:
                raise ConnectionError("Guest 文件超过允许的传输上限")
        return bytes(collected)


def put_url(url, payload, context=None, allow_plain_http=False):
    enforce_target(url, None, allow_plain_http=allow_plain_http)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https":
        connection = http.client.HTTPSConnection(
            parts.hostname, parts.port or 443, context=context, timeout=60)
    else:
        connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=60)
    path = parts.path + (("?" + parts.query) if parts.query else "")
    headers = {"Content-Length": str(len(payload)),
               "Content-Type": "application/octet-stream"}
    with closing(connection):
        connection.request("PUT", path, body=payload, headers=headers)
        response = connection.getresponse()
        status = response.status
        if status not in (200, 201, 204):
            raise ConnectionError(f"Guest 文件上传被拒绝：HTTP {status}")
        return status
