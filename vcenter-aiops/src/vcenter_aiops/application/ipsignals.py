"""IP availability signals for scoped networks.

A ping result is only a signal; inconclusive evidence must never be reported
as "free". Dependencies are injected so the logic is testable without a host.
"""
import re
import subprocess
import sys
import time

from ..domain.models import fail


def ping_probe(address):
    """Return True/False for a clear result, None when probing is unavailable."""
    count = "-n" if sys.platform.startswith("win") else "-c"
    wait = ["-w", "2000"] if sys.platform.startswith("win") else ["-W", "2"]
    command = ["ping", count, "1"] + wait + [address]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=4)
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.returncode == 0


class IpSignals:
    def __init__(self, store, vm_items, pinger=ping_probe, now=time.time):
        self.store = store
        self.vm_items = vm_items
        self.pinger = pinger
        self.now = now

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
