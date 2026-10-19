"""H-2 regression: profile TLS config must reach the Guest transfer connection.

A private-CA / self-signed profile supplies ``ca_file`` (or verify_tls=false),
which ``Guest._context`` turns into an ssl.SSLContext. get_url/put_url MUST pass
that object through to ``http.client.HTTPSConnection``; dropping it silently
falls back to the system trust store and breaks (or tempts disabling) real
transfers. These tests capture the constructor kwargs with a fake connection.
"""
import ssl
import unittest
from unittest.mock import patch

from vcenter_aiops.providers.vsphere import guest_http


class FakeResponse:
    def __init__(self, status=200, body=b"ok"):
        self.status = status
        self._body = body

    def read(self, chunk=None):
        body, self._body = self._body, b""
        return body


class FakeConnection:
    calls = []

    def __init__(self, host, port=None, **kwargs):
        self.kwargs = kwargs
        FakeConnection.calls.append((host, port, kwargs))
        self._status = kwargs.pop("_status", 200)

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        return FakeResponse()

    def close(self):
        pass


class TlsPassthroughTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.calls = []

    def _patch(self):
        return patch("vcenter_aiops.providers.vsphere.guest_http.http.client.HTTPSConnection",
                     FakeConnection)

    def test_get_url_passes_custom_context_through(self):
        ctx = guest_http.ssl_context(verify_tls=False)
        with self._patch():
            guest_http.get_url("https://vcenter.example:443/x?ticket=abc", context=ctx)
        self.assertEqual(len(FakeConnection.calls), 1)
        _, _, kwargs = FakeConnection.calls[0]
        self.assertIs(kwargs["context"], ctx)

    def test_put_url_passes_custom_context_through(self):
        ctx = guest_http.ssl_context(verify_tls=False)
        with self._patch():
            guest_http.put_url("https://vcenter.example/x?t=1", b"body", context=ctx)
        self.assertEqual(len(FakeConnection.calls), 1)
        _, _, kwargs = FakeConnection.calls[0]
        self.assertIs(kwargs["context"], ctx)

    def test_no_dead_connection_helper_that_drops_context(self):
        # The only connection builders are get_url/put_url; there must be no
        # leftover helper that constructs HTTPSConnection without a context.
        self.assertFalse(hasattr(guest_http, "_connection"))

    def test_ssl_context_refuses_verification_when_disabled(self):
        ctx = guest_http.ssl_context(verify_tls=False)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)

    def test_ssl_context_requires_verification_by_default(self):
        ctx = guest_http.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
