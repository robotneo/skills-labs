from __future__ import absolute_import

import platform
import socket
import time
from urllib.request import urlopen

from .parsers import parse_ping


def ping_target(runner, target, count=3):
    if not target:
        return None
    if platform.system().lower() == "windows":
        args = ["ping", "-n", str(count), "-w", "1000", target]
    else:
        args = ["ping", "-c", str(count), "-W", "1000", target]
    result = runner.run(args, timeout=max(5, count * 2))
    parsed = parse_ping((result.stdout or "") + "\n" + (result.stderr or ""))
    parsed["reachable"] = parsed["packet_loss_percent"] < 100
    parsed["source"] = "ping"
    return parsed


def dns_test(host="www.example.com"):
    start = time.monotonic()
    try:
        socket.getaddrinfo(host, 443)
        return {"reachable": True, "latency_ms": round((time.monotonic() - start) * 1000, 2)}
    except OSError as exc:
        return {"reachable": False, "latency_ms": None, "reason": str(exc)}


def speed_test(timeout=8):
    url = "https://speed.cloudflare.com/__down?bytes=1000000"
    start = time.monotonic()
    try:
        with urlopen(url, timeout=timeout) as response:
            received = len(response.read(1000000))
        elapsed = max(time.monotonic() - start, 0.001)
        return round(received * 8.0 / elapsed / 1000000.0, 2)
    except Exception:
        return None
