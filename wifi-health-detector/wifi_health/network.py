from __future__ import absolute_import

import platform
import re
import subprocess
import sys
import time
import os
import ipaddress
import json
import math

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


def dns_test(host, timeout=10):
    # Use the same bounded OS resolver commands as the portable engines.
    if timeout <= 0:
        return {"reachable": False, "latency_ms": None, "reason": "total time budget exhausted"}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
        return {"reachable": False, "latency_ms": None, "reason": "invalid DNS name"}
    try:
        macos = platform.system() == "Darwin"
        helper = os.path.join(os.path.dirname(os.path.dirname(__file__)), "portable", "dns.ps1")
        command = (["/usr/bin/dscacheutil", "-q", "host", "-a", "name", host] if macos else
                   ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", helper, host])
        start = time.monotonic()
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True,
                                errors="replace", timeout=timeout, shell=False)
        answer = result.stdout or ""
        # A zero exit code alone does not prove the resolver found a record.
        payload = {} if macos else json.loads(answer)
        addresses = re.findall(r"(?:ip_address|ipv6_address):\s*(\S+)", answer) if macos else payload.get('addresses', [])
        resolved = bool(addresses) and all(ipaddress.ip_address(address) for address in addresses)
        if result.returncode or not resolved:
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
    try:
        script = "import time,sys; from urllib.request import urlopen; start=time.monotonic(); response=urlopen('https://speed.cloudflare.com/__down?bytes=1000000',timeout=float(sys.argv[1])); received=len(response.read(1000000)); print(round(received*8/max(time.monotonic()-start,0.001)/1000000,2))"
        result = subprocess.run([sys.executable, "-c", script, str(timeout)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
        return float(result.stdout.strip()) if result.returncode == 0 else None
    except Exception:
        return None
