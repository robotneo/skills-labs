"""Read-only, narrow entitlement evidence from exact license assignments.

Accepted feature shape: repeated properties["feature"] containing vim.KeyValue.
Broadcom govmomi simulator/license_manager.go demonstrates that SDK shape;
vim25/types/enum.go defines the drs and vmotion tokens. No deprecated probe is
called. Only a single timezone-aware expirationDate proves bounded validity.
Relative expiry, start dates, server clocks, and perpetual markers are unsupported
and rejected rather than ignored. This intentionally does not accept every
property shape shown in KB 381426 or every commercial/perpetual license.
"""
from datetime import datetime, timezone
import re

from ...domain.models import OperationError, fail


FEATURES = frozenset(("drs", "vmotion", "das"))  # HA token: Broadcom KB 381426.
METADATA = frozenset(("ProductName", "ProductVersion", "ComponentFamily"))


class Licenses:
    def __init__(self, content, now=None):
        self.content = content
        self.now = now or (lambda: datetime.now(timezone.utc))

    def require(self, entity_id, features, server_uuid):
        try:
            return self._require(entity_id, features, server_uuid)
        except OperationError:
            raise
        except Exception:
            # SDK faults and arbitrary additional properties can contain keys.
            raise OperationError("license_unknown", "无法安全读取或解释精确实体的许可证据", 4) from None

    def _require(self, entity_id, features, server_uuid):
        required = set(features)
        if (not isinstance(entity_id, str) or not re.fullmatch(r"host-\d+", entity_id)
                or not required or not required <= FEATURES):
            fail("license_unknown", "当前许可适配器不支持此实体或功能", 4)
        manager = getattr(getattr(self.content, "licenseManager", None), "licenseAssignmentManager", None)
        query = getattr(manager, "QueryAssignedLicenses", None)
        if not callable(query):
            fail("license_unknown", "精确实体的许可分配查询不可用", 4)
        rows = query(entityId=entity_id)
        if not isinstance(rows, (list, tuple)) or len(rows) != 1:
            fail("license_unknown", "许可分配证据缺失或不唯一", 4)
        row = rows[0]
        scope = getattr(row, "scope", None)
        if getattr(row, "entityId", None) != entity_id or scope not in (None, server_uuid):
            fail("license_unknown", "许可分配不属于精确实体或当前 vCenter", 4)
        license_info = getattr(row, "assignedLicense", None)
        return {"entity_id": entity_id, "scope": scope, **self._evidence(license_info, required)}

    def _evidence(self, license_info, required):
        from pyVmomi import vim

        total = getattr(license_info, "total", None)
        used = getattr(license_info, "used", None)
        unit = getattr(license_info, "costUnit", None)
        if (not isinstance(total, int) or isinstance(total, bool) or total <= 0
                or unit not in ("cpuPackage", "cpuCore", "host", "server")
                or (used is not None and (not isinstance(used, int) or isinstance(used, bool)
                                          or not 0 <= used <= total))):
            fail("license_unknown", "许可容量或计量单位缺失、无效或尚不支持", 4)
        properties = getattr(license_info, "properties", None)
        if not isinstance(properties, (list, tuple)):
            fail("license_unknown", "许可功能与有效期证据缺失", 4)
        granted, expiration = set(), []
        for prop in properties:
            key = getattr(prop, "key", None)
            if key in ("diagnostic", "license_not_set"):
                fail("license_denied", "许可包含未满足或无效分配诊断", 4)
            if key == "feature":
                value = getattr(prop, "value", None)
                if not isinstance(value, vim.KeyValue) or not isinstance(value.key, str) or not value.key:
                    fail("license_unknown", "许可功能证据格式尚不支持", 4)
                if value.key in granted:
                    fail("license_unknown", "许可功能证据重复或不唯一", 4)
                granted.add(value.key)
            elif key == "expirationDate":
                expiration.append(getattr(prop, "value", None))
            elif not isinstance(key, str) or key not in METADATA:
                fail("license_unknown", "许可包含尚无法解释的属性", 4)
        if len(expiration) != 1:
            fail("license_unknown", "无法判定许可有效期；不推断永久许可", 4)
        expiry = expiration[0]
        if isinstance(expiry, str):
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if not isinstance(expiry, datetime) or expiry.tzinfo is None:
            fail("license_unknown", "许可有效期格式尚不支持", 4)
        expiry = expiry.astimezone(timezone.utc)
        if expiry <= self.now():
            fail("license_denied", "精确实体的许可已过期", 4)
        if not required <= granted:
            fail("license_denied", "精确实体缺少所需的功能授权证据", 4)
        # Only stable, allowlisted evidence is bound. Never inspect licenseKey,
        # return descriptions/labels, or bind a clock/current usage counter.
        return {"features": sorted(required),
                "total": total, "cost_unit": unit, "expires_at": expiry.isoformat()}
