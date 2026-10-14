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


def ssl_context(verify_tls=True, ca_file=None):
    if not verify_tls:
        context = ssl._create_unverified_context()
    elif ca_file:
        context = ssl.create_default_context(cafile=ca_file)
    else:
        context = ssl.create_default_context()
    return context


def put_file(url, source_path, headers, context=None, chunk=1024 * 1024):
    """PUT a local file to an NFC device URL, following up to 4 redirects.

    Redirects switch the Host header but keep the session Cookie (NFC targets the
    ESXi host which still accepts the vCenter session ticket for import).
    """
    remaining = 4
    current = url
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
                    raise ConnectionError("NFC 上传重定向次数过多")
                remaining -= 1
                current = urllib.parse.urljoin(current, response.getheader("Location"))
                continue
            if status not in (200, 201, 204):
                raise ConnectionError(f"NFC 上传被拒绝：HTTP {status}")
            return status


def _reader(stream, chunk):
    while True:
        block = stream.read(chunk)
        if not block:
            break
        yield block
