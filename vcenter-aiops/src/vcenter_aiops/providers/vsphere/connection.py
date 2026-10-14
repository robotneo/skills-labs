import ssl

from ...domain.models import fail
from ...infrastructure.credentials import resolve_credential


class Session:
    def __init__(self, profile, timeout=30):
        self.profile = profile
        self.timeout = timeout
        self.si = None

    def __enter__(self):
        try:
            from pyVim.connect import SmartConnect
        except ImportError:
            fail("dependency_missing", "请安装项目依赖后连接 vCenter", 3)
        password = resolve_credential(self.profile["password_ref"])
        try:
            context = ssl.create_default_context(cafile=self.profile.get("ca_file"))
            if not self.profile.get("verify_tls", True):
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            self.si = SmartConnect(host=self.profile["host"], user=self.profile["user"], pwd=password,
                                   port=self.profile.get("port", 443), sslContext=context,
                                   httpConnectionTimeout=self.timeout)
        except Exception:
            # SDK exceptions can contain endpoints and credential material.
            fail("connection_failed", "连接失败，请检查凭据、证书和网络", 3)
        return self.si

    def __exit__(self, *args):
        from pyVim.connect import Disconnect
        if self.si is not None:
            try:
                Disconnect(self.si)
            except Exception:
                pass
            self.si = None


def server_info(si, content=None):
    # Reuse ServiceContent the caller already fetched (every provider caches
    # it at construction) to avoid a second RetrieveContent SOAP round trip per
    # read command; fall back to fetching it when nothing is supplied.
    about = (content or si.RetrieveContent()).about
    return {"instance_uuid": about.instanceUuid, "api_version": about.apiType,
            "version": about.version, "build": about.build, "api_type": about.apiType,
            "validation_status": "not_lab_verified"}
