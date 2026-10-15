from __future__ import absolute_import

import platform
import re
import subprocess
import time
import os
import ipaddress
import json
import math
from urllib import request as _url_request

from .parsers import parse_ping


def ping_target(runner, target, count=3):
    if not target:
        return None
    if platform.system().lower() == "windows":
        args = ["ping", "-n", str(count), "-w", "1000", target]
    else:
        args = ["ping", "-c", str(count), "-W", "1000", target]
    result = runner.run(args, timeout=max(5, count * 2))
    if result.error or result.returncode in (124, 127) or re.search(r"transmit failed|general failure|permission denied|operation not permitted|sendto:|network is unreachable|传输失败|常见故障|一般故障|拒绝访问", result.stdout + result.stderr, re.I):
        return None
    if not re.search(r"[\d.]+%\s*(?:packet loss|loss|丢失)", result.stdout, re.I):
        return None
    parsed = parse_ping((result.stdout or "") + "\n" + (result.stderr or ""))
    parsed["reachable"] = parsed["packet_loss_percent"] < 100
    parsed["source"] = "ping"
    return parsed


def _dns_command(host):
    """Return (is_macos, bounded OS-resolver command) shared with the engines."""
    if platform.system() == "Darwin":
        return True, ["/usr/bin/dscacheutil", "-q", "host", "-a", "name", host]
    helper = os.path.join(os.path.dirname(os.path.dirname(__file__)), "portable", "dns.ps1")
    return False, ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", helper, host]


def dns_test(host, timeout=10, runner=None):
    # Use the same bounded OS resolver commands as the portable engines. When a
    # CommandRunner is supplied the probe is governed by the shared total budget
    # and descendant cleanup; otherwise it runs directly (standalone/test use).
    if timeout <= 0:
        return {"reachable": False, "latency_ms": None, "reason": "total time budget exhausted"}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
        return {"reachable": False, "latency_ms": None, "reason": "invalid DNS name"}
    macos, command = _dns_command(host)
    start = time.monotonic()
    try:
        if runner is not None:
            result = runner.run(command, timeout=timeout)
            if result.error or result.returncode in (124, 127):
                return {"reachable": False, "latency_ms": None, "reason": result.error or "DNS command timed out"}
            answer, returncode = result.stdout or "", result.returncode
        else:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, universal_newlines=True,
                                    errors="replace", timeout=timeout, shell=False)
            answer, returncode = result.stdout or "", result.returncode
        # A zero exit code alone does not prove the resolver found a record.
        payload = {} if macos else json.loads(answer)
        addresses = re.findall(r"(?:ip_address|ipv6_address):\s*(\S+)", answer) if macos else payload.get('addresses', [])
        resolved = bool(addresses) and all(ipaddress.ip_address(address) for address in addresses)
        if returncode or not resolved:
            return {"reachable": False, "latency_ms": None, "reason": "DNS lookup failed"}
        latency = round((time.monotonic() - start) * 1000, 2) if macos else float(payload['latency_ms'])
        if not math.isfinite(latency) or latency < 0:
            raise ValueError('invalid DNS duration')
        return {"reachable": True, "latency_ms": latency}
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"reachable": False, "latency_ms": None, "reason": str(exc)}


def speed_test(timeout=8):
    if timeout <= 0:
        return None
    # In-process stdlib download: avoid a cold Python "-c" subprocess while still
    # bounding wall time. Any failure yields None, mirroring the previous path.
    # The only destination is Cloudflare's public speed-test endpoint, already
    # documented in SKILL.md; nothing is uploaded.
    deadline = time.monotonic() + timeout
    try:
        url = "https://speed.cloudflare.com/__down?bytes=1000000"
        response = _url_request.urlopen(url, timeout=max(0.1, timeout))
        with response:
            start = time.monotonic()
            received = 0
            while received < 1_000_000:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                chunk = response.read(65536)
                if not chunk:
                    break
                received += len(chunk)
            elapsed = max(time.monotonic() - start, 0.001)
            return round(received * 8 / elapsed / 1_000_000, 2)
    except Exception:
        return None
