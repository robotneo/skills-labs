from __future__ import absolute_import

import platform
import re
import subprocess
import sys
import json

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
    # A subprocess, rather than an uncancellable getaddrinfo thread, bounds DNS.
    if timeout <= 0:
        return {"reachable": False, "latency_ms": None, "reason": "total time budget exhausted"}
    try:
        script = "import socket,time,json,sys; start=time.monotonic(); socket.getaddrinfo(sys.argv[1],443); print(json.dumps({'reachable':True,'latency_ms':round((time.monotonic()-start)*1000,2)}))"
        result = subprocess.run([sys.executable, "-c", script, host], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
        if result.returncode:
            return {"reachable": False, "latency_ms": None, "reason": "DNS lookup failed"}
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
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
