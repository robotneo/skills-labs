"""IP availability signals for scoped networks.

A ping result is only a signal; inconclusive evidence must never be reported
as "free". Dependencies are injected so the logic is testable without a host.
"""
import functools
import ipaddress
import os
import re
import subprocess
import sys
import time

from ..domain.models import fail


# L-8: the ping wall-clock budget was a hard-coded subprocess timeout. It is now
# a configurable ceiling (env override, clamped). The per-reply ping wait (-W/-w)
# is capped to this budget so the subprocess timeout stays the binding limit;
# an expired/launch failure still yields an inconclusive (None) signal.
DEFAULT_PING_TIMEOUT = 4
MIN_PING_TIMEOUT = 1
MAX_PING_TIMEOUT = 30
_PING_TIMEOUT_ENV = "VCENTER_AIOPS_PING_TIMEOUT"


def resolve_ping_timeout():
    """Ping wall-clock budget in seconds from the env, clamped to a safe window.

    Invalid / non-positive values fall back to the default so a misconfiguration
    cannot disable the ceiling or force an unbounded probe.
    """
    raw = os.environ.get(_PING_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_PING_TIMEOUT
    try:
        seconds = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_PING_TIMEOUT
    return max(MIN_PING_TIMEOUT, min(seconds, MAX_PING_TIMEOUT))


def require_ip_address(address):
    """Reject anything that is not a literal IPv4/IPv6 address.

    The address is later passed as an argv element to ``ping`` (never through a
    shell), but a value beginning with ``-`` would still be parsed by ping as an
    option. Validating at this boundary prevents option/argument injection.
    """
    if not isinstance(address, str):
        fail("invalid_arguments", "address 必须是字面 IPv4/IPv6 地址", 2)
    try:
        ipaddress.ip_address(address)
    except ValueError:
        fail("invalid_arguments", "address 必须是合法的字面 IPv4/IPv6 地址，不接受主机名或选项", 2)
    return address


def ping_probe(address, timeout=DEFAULT_PING_TIMEOUT):
    """Return True/False for a clear result, None when probing is unavailable."""
    require_ip_address(address)
    is_win = sys.platform.startswith("win")
    count = "-n" if is_win else "-c"
    if is_win:
        # -w is the per-reply timeout in milliseconds; cap it at the hard budget.
        wait = ["-w", str(max(MIN_PING_TIMEOUT * 1000, min(timeout * 1000, 2000)))]
    else:
        # -W is the per-reply wait in whole seconds; never exceed the hard budget.
        wait = ["-W", str(max(MIN_PING_TIMEOUT, min(timeout, 2)))]
    command = ["ping", count, "1"] + wait + [address]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.returncode == 0


class IpSignals:
    def __init__(self, store, vm_items, pinger=ping_probe, now=time.time,
                 ping_timeout=None):
        self.store = store
        self.vm_items = vm_items
        self.now = now
        self.ping_timeout = ping_timeout or resolve_ping_timeout()
        # Bind the configurable budget only around the built-in probe; an
        # injected pinger (offline seam) keeps its single-argument contract.
        self.pinger = (functools.partial(ping_probe, timeout=self.ping_timeout)
                       if pinger is ping_probe else pinger)

    def _inventory_use(self, address):
        output = []
        pattern = re.compile(r"(?<![\d.])" + re.escape(address) + r"(?![\d.])")
        for row in self.vm_items:
            ip_match = row.get("guest.ipAddress") == address
            name_match = bool(pattern.search(row.get("name") or ""))
            if ip_match or name_match:
                output.append({"vm_id": row.get("id"), "name": row.get("name"),
                               "by_ip": ip_match, "by_name": name_match})
        return output

    def _active_lease(self, scope, address):
        moment = self.now()
        for lease in self.store.leases(scope):
            if lease["ip"] != address:
                continue
            expires = lease["expires"]
            if expires is None or expires > moment:
                return {"lease_id": lease["token"], "owner": lease["owner"]}
        return None

    def check(self, address, scope):
        require_ip_address(address)
        ping = self.pinger(address)
        return {
            "address": address, "scope": scope,
            "inventory_use": self._inventory_use(address),
            "active_lease": self._active_lease(scope, address),
            "ping": {"reachable": ping} if ping is not None
            else {"reachable": None, "inconclusive": True},
            "collected_at": self.now(),
        }

    def available(self, address, scope):
        require_ip_address(address)
        inventory_use = self._inventory_use(address)
        lease = self._active_lease(scope, address)
        ping = self.pinger(address)
        response = {"address": address, "scope": scope,
                    "available": False, "inconclusive": False,
                    "reasons": [], "collected_at": self.now()}
        if inventory_use:
            response["reasons"].append("inventory_use")
        if lease:
            response["reasons"].append("active_lease")
        if ping is None:
            response["inconclusive"] = True
            response["available"] = False
            response["reasons"].append("ping_inconclusive")
        elif ping:
            response["reasons"].append("ping_reachable")
        else:
            if not response["reasons"]:
                response["available"] = True
        return response

    def expired(self):
        moment = self.now()
        items = [{"lease_id": lease["token"], "scope": lease["scope"],
                  "ip": lease["ip"], "owner": lease["owner"],
                  "expires": lease["expires"]}
                 for lease in self.store.leases()
                 if lease["expires"] is not None and lease["expires"] < moment]
        return {"items": items, "count": len(items)}

    def expire_release(self, lease_id):
        listing = self.expired()
        match = next((item for item in listing["items"]
                      if item["lease_id"] == lease_id), None)
        if match is None:
            fail("lease_not_expired", "指定租约不存在或尚未过期；不释放", 2)
        self.store.release(lease_id)
        return {"released": lease_id, "scope": match["scope"],
                "ip": match["ip"]}
