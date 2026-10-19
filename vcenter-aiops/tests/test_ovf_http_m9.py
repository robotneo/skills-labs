"""M-9 regression: harden the dependency-free OVF/Guest HTTP transfer boundary.

NFC/Guest upload URLs come from the vCenter lease and can carry 3xx redirects.
A downgrade (https -> http) or a cross-host redirect can leak credentials or the
VM payload, and an open redirect loop can pin the client. Both transport helpers
therefore MUST, by default:

* reject a plain ``http`` URL unless the caller explicitly opts in,
* follow only same-scheme (https) redirects,
* pin every hop's host to an allow-set (the first URL host, or an explicit
  vCenter/ESXi host set),
* pass the caller TLS ``context`` on every hop,
* cap redirect hops.

This module already implemented those guards at the 3.0.0b4 baseline; these
tests lock the behavior against regressions rather than change production code.
"""
import contextlib
import os
import ssl
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.providers.vsphere import guest_http, ovf_http
from vcenter_aiops.providers.vsphere.ovf_deploy import OvfDeploy


class FakeResponse:
    def __init__(self, status=200, location=None):
        self.status = status
        self._location = location

    def getheader(self, name):
        if name.lower() == "location":
            return self._location
        return None

    def read(self, chunk=None):
        return b""


class ScriptedConnections:
    """Records calls and serves a per-host scripted list of responses."""

    def __init__(self):
        self.calls = []          # (kind, host, port, kwargs)
        self.script = {}         # host -> list[FakeResponse]

    def _make(self, kind):
        outer = self

        class FakeConn:
            def __init__(self, host, port=None, **kwargs):
                self.host = host
                outer.calls.append((kind, host, port, kwargs))
                self.kwargs = kwargs

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                queue = outer.script.get(self.host)
                if queue:
                    return queue.pop(0)
                return FakeResponse()

            def close(self):
                pass

        return FakeConn

    def patch(self, target_module):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(
            target_module.http.client, "HTTPSConnection", self._make("https")))
        stack.enter_context(patch.object(
            target_module.http.client, "HTTPConnection", self._make("http")))
        return stack


class OvfPutFileSchemeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self.tmp.name, "disk.vmdk")
        with open(self.src, "wb") as handle:
            handle.write(b"disk-bytes")
        self.net = ScriptedConnections()

    def tearDown(self):
        self.tmp.cleanup()

    def _put(self, url, **kwargs):
        with self.net.patch(ovf_http):
            return ovf_http.put_file(url, self.src,
                                     headers={"Overwrite": "t"}, **kwargs)

    def test_plain_http_rejected_by_default(self):
        with self.assertRaises(ovf_http.TransferError) as raised:
            self._put("http://esxi.example/nfc/disk.vmdk")
        self.assertEqual(raised.exception.code, "transfer_scheme_denied")
        self.assertEqual([c for c in self.net.calls], [])

    def test_plain_http_requires_explicit_informed_opt_in(self):
        # Even when allowed, no TLS context applies and the attempt is recorded.
        self._put("http://esxi.example/nfc/disk.vmdk", allow_plain_http=True)
        kinds = [c[0] for c in self.net.calls]
        self.assertIn("http", kinds)

    def test_first_host_is_pinned_as_default_allow_set(self):
        # A redirect to a different host is refused even over https.
        self.net.script["vcenter.example"] = [
            FakeResponse(302, "https://evil.example/nfc/disk.vmdk")]
        with self.assertRaises(ovf_http.TransferError) as raised:
            self._put("https://vcenter.example/nfc/disk.vmdk")
        self.assertEqual(raised.exception.code, "redirect_host_denied")

    def test_redirect_downgrade_to_http_is_refused(self):
        self.net.script["vcenter.example"] = [
            FakeResponse(302, "http://vcenter.example/nfc/disk.vmdk")]
        with self.assertRaises(ovf_http.TransferError) as raised:
            self._put("https://vcenter.example/nfc/disk.vmdk")
        self.assertEqual(raised.exception.code, "redirect_scheme_denied")

    def test_same_host_https_redirect_followed_with_context_each_hop(self):
        ctx = ovf_http.ssl_context(verify_tls=False)
        self.net.script["vcenter.example"] = [
            FakeResponse(302, "https://vcenter.example/nfc/relocated.vmdk")]
        self._put("https://vcenter.example/nfc/disk.vmdk", context=ctx)
        https_calls = [c for c in self.net.calls if c[0] == "https"]
        self.assertEqual(len(https_calls), 2)
        for _, _, _, kwargs in https_calls:
            self.assertIs(kwargs["context"], ctx)

    def test_explicit_allow_set_permits_additional_esxi_host(self):
        ctx = ovf_http.ssl_context(verify_tls=False)
        self.net.script["vcenter.example"] = [
            FakeResponse(307, "https://esxi-01.example/nfc/disk.vmdk")]
        self._put("https://vcenter.example/nfc/disk.vmdk", context=ctx,
                  allowed_hosts=["vcenter.example", "esxi-01.example"])
        hosts = [c[1] for c in self.net.calls if c[0] == "https"]
        self.assertEqual(hosts, ["vcenter.example", "esxi-01.example"])

    def test_redirect_loop_is_capped(self):
        # Always bounce to a fresh path on the same https host: hop budget wins.
        self.net.script["vcenter.example"] = [
            FakeResponse(302, "https://vcenter.example/nfc/a"),
            FakeResponse(302, "https://vcenter.example/nfc/b"),
            FakeResponse(302, "https://vcenter.example/nfc/c"),
            FakeResponse(302, "https://vcenter.example/nfc/d"),
            FakeResponse(302, "https://vcenter.example/nfc/e"),
        ]
        with self.assertRaises(ovf_http.TransferError) as raised:
            self._put("https://vcenter.example/nfc/start")
        self.assertEqual(raised.exception.code, "transfer_redirect_loop")


class GuestTransferSchemeTests(unittest.TestCase):
    def setUp(self):
        self.net = ScriptedConnections()

    def _patch(self, module):
        return self.net.patch(module)

    def test_get_url_plain_http_rejected_by_default(self):
        with self._patch(guest_http):
            with self.assertRaises(guest_http.TransferError) as raised:
                guest_http.get_url("http://esxi.example/guest/file")
        self.assertEqual(raised.exception.code, "transfer_scheme_denied")

    def test_get_url_https_passes_context(self):
        ctx = guest_http.ssl_context(verify_tls=False)
        with self._patch(guest_http):
            guest_http.get_url("https://esxi.example/guest/file", context=ctx)
        https_calls = [c for c in self.net.calls if c[0] == "https"]
        self.assertEqual(len(https_calls), 1)
        self.assertIs(https_calls[0][3]["context"], ctx)

    def test_put_url_plain_http_rejected_by_default(self):
        with self._patch(guest_http):
            with self.assertRaises(guest_http.TransferError) as raised:
                guest_http.put_url("http://esxi.example/guest/file", b"x")
        self.assertEqual(raised.exception.code, "transfer_scheme_denied")

    def test_put_url_http_opt_in_is_explicit(self):
        with self._patch(guest_http):
            guest_http.put_url("http://esxi.example/guest/file", b"x",
                               allow_plain_http=True)
        self.assertIn("http", [c[0] for c in self.net.calls])

    def test_ssl_context_default_requires_verification(self):
        ctx = guest_http.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)


class _FakeAbout:
    instanceUuid = "uuid-1"


class _FakeContent:
    def __init__(self):
        self.about = _FakeAbout()


class _FakeSi:
    def __init__(self, stub_host):
        self._stub = type("Stub", (), {"host": stub_host})()

    def RetrieveContent(self):
        return _FakeContent()


class OvfDeployAllowSetTests(unittest.TestCase):
    """The deploy uploader must pre-authorize vCenter + the lease deviceUrl host.

    This drives the REAL ovf_http.put_file (only http.client is faked) to prove
    the allow-set built by OvfDeploy admits the authentic vCenter->ESXi redirect
    but rejects a pivot to an unrelated host.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.disk = os.path.join(self.tmp.name, "disk.vmdk")
        with open(self.disk, "wb") as handle:
            handle.write(b"x")
        self.net = ScriptedConnections()

    def tearDown(self):
        self.tmp.cleanup()

    def _uploader(self, stub_host="https://vcenter.example/sdk"):
        provider = OvfDeploy(_FakeSi(stub_host), resolver=lambda *a: None)
        return provider._make_upload({}, self.tmp.name)

    def test_authentic_vcenter_to_esxi_redirect_accepted(self):
        self.net.script["esxi-01.example"] = [FakeResponse(200)]
        target = {"file": "disk.vmdk", "url": "https://esxi-01.example/nfc/d"}
        with self.net.patch(ovf_http):
            self._uploader()(target, None)
        hosts = [c[1] for c in self.net.calls]
        self.assertEqual(hosts, ["esxi-01.example"])

    def test_redirect_pivot_from_authorized_to_foreign_host_rejected(self):
        # First hop is the lease-issued ESXi host; it tries to bounce to an
        # attacker host that is neither vCenter nor any deviceUrl endpoint.
        self.net.script["esxi-01.example"] = [
            FakeResponse(302, "https://evil.example/exfil")]
        target = {"file": "disk.vmdk", "url": "https://esxi-01.example/nfc/d"}
        with self.net.patch(ovf_http):
            with self.assertRaises(ovf_http.TransferError) as raised:
                self._uploader()(target, None)
        self.assertEqual(raised.exception.code, "redirect_host_denied")
        self.assertNotIn("evil.example", [c[1] for c in self.net.calls])

    def test_plain_http_device_url_rejected_even_with_allow_set(self):
        target = {"file": "disk.vmdk", "url": "http://esxi-01.example/nfc/d"}
        with self.net.patch(ovf_http):
            with self.assertRaises(ovf_http.TransferError) as raised:
                self._uploader()(target, None)
        self.assertEqual(raised.exception.code, "transfer_scheme_denied")


if __name__ == "__main__":
    unittest.main()
