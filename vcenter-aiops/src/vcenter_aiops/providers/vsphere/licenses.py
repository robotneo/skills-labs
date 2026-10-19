"""Read-only, narrow entitlement evidence from exact license assignments.

Evidence is gathered from ``QueryAssignedLicenses`` and accepted only when there
is *positive* proof that every required feature is granted to the exact entity by
a non-expired assignment on the current vCenter. The adapter never grants on the
absence of data ("查不到就允许" is explicitly impossible here).

Accepted real-world shapes (8.0.3):

* 0..N assignment rows are aggregated instead of demanding exactly one. Cluster
  /suite features are commonly spread across rows; features are unioned across
  every row whose ``entityId`` matches and whose ``scope`` is the current vCenter
  (or unscoped). A foreign-entity / foreign-vCenter row is never counted.
* Unknown ``properties`` keys are ignored (only ``feature``, ``expirationDate``
  and the deny markers are interpreted) instead of failing the whole read.
* A license with **no** ``expirationDate`` is treated as non-expiring (perpetual /
  subscription without a bound the server reports). It still grants nothing by
  itself -- the repeated ``feature`` properties remain the positive evidence.
  A concrete ``expirationDate`` that is present but unparseable keeps the adapter
  fail-closed (it cannot be mistaken for perpetual).

``diagnostic`` / ``license_not_set`` remain hard denials. Expired rows grant no
features. With zero usable rows the result is ``license_unverifiable``: the
adapter never infirms a permission, it simply cannot prove one.
"""
from datetime import datetime, timezone
import re

from ...domain.models import OperationError, fail


FEATURES = frozenset(("drs", "vmotion", "das"))  # HA token: Broadcom KB 381426.
METADATA = frozenset(("ProductName", "ProductVersion", "ComponentFamily"))
# Properties that, when present on an assignment, prove the assignment is
# unsatisfied/invalid regardless of any feature tokens in the same row.
DENY_MARKERS = frozenset(("diagnostic", "license_not_set"))


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
        if not isinstance(rows, (list, tuple)):
            fail("license_unknown", "许可分配证据格式无效", 4)

        matching = [row for row in rows
                    if getattr(row, "entityId", None) == entity_id
                    and getattr(row, "scope", None) in (None, server_uuid)]
        if not matching:
            # No row attributable to this exact entity on this vCenter. Do not
            # guess (cluster-level/suite-only coverage is verified elsewhere);
            # report the accurate "unverifiable" condition while still denying.
            fail("license_unverifiable", "精确实体在当前 vCenter 上没有可归因的许可分配证据", 4)

        granted, terms = set(), []
        for row in matching:
            features_row, term = self._row_evidence(row)
            granted |= features_row
            terms.append(term)
        if not required <= granted:
            fail("license_denied", "精确实体缺少所需的功能授权证据", 4)
        # Only stable, allowlisted evidence is bound. Never inspect licenseKey,
        # return descriptions/labels, or bind a clock/current usage counter.
        return {"entity_id": entity_id, "features": sorted(required), "licenses": terms}

    def _row_evidence(self, row):
        """Return (granted_features, bound_term) for one matching assignment.

        An expired row contributes no features. Malformed capacity/feature shapes
        and deny markers remain fail-closed.
        """
        from pyVmomi import vim

        license_info = getattr(row, "assignedLicense", None)
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

        granted, expiration_values, saw_expiry_key = set(), [], False
        for prop in properties:
            key = getattr(prop, "key", None)
            if key in DENY_MARKERS:
                fail("license_denied", "许可包含未满足或无效分配诊断", 4)
            if key == "feature":
                value = getattr(prop, "value", None)
                if not isinstance(value, vim.KeyValue) or not isinstance(value.key, str) or not value.key:
                    fail("license_unknown", "许可功能证据格式尚不支持", 4)
                granted.add(value.key)
            elif key == "expirationDate":
                saw_expiry_key = True
                expiration_values.append(getattr(prop, "value", None))
            # Any other key (metadata or an unknown 8.0.3 property) is ignored:
            # consuming only allowlisted evidence is the safe relaxation.

        perpetual = not saw_expiry_key
        if len(expiration_values) > 1:
            fail("license_unknown", "单个许可分配的有效期证据不唯一", 4)
        expires_at = None
        if not perpetual:
            raw = expiration_values[0]
            expiry = raw
            if isinstance(expiry, str):
                try:
                    expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                except ValueError:
                    expiry = None
            if not isinstance(expiry, datetime) or expiry.tzinfo is None:
                # A concrete expiry we cannot parse must never read as perpetual.
                fail("license_unknown", "许可有效期格式尚不支持", 4)
            expiry = expiry.astimezone(timezone.utc)
            if expiry <= self.now():
                # Expired assignments grant no features; term is still recorded.
                return set(), {"total": total, "cost_unit": unit,
                               "expires_at": expiry.isoformat(), "perpetual": False,
                               "scope": getattr(row, "scope", None)}
            expires_at = expiry.isoformat()
        return granted, {"total": total, "cost_unit": unit, "expires_at": expires_at,
                         "perpetual": perpetual, "scope": getattr(row, "scope", None)}
