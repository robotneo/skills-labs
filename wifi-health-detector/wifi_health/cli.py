from __future__ import absolute_import, print_function

import argparse
import sys

from .collectors import collect_report
from .command import CommandRunner
from .diagnose import diagnose
from .network import dns_test, ping_target, speed_test
from .output import render_csv, render_json, render_text


def build_parser():
    parser = argparse.ArgumentParser(description="Cross-platform Wi-Fi health detector")
    parser.add_argument("--interface", help="override the automatically detected Wi-Fi interface")
    parser.add_argument("--speedtest", action="store_true", help="run an optional 1 MB throughput test")
    parser.add_argument("--no-public-test", action="store_true", help="skip DNS and public connectivity tests")
    parser.add_argument("--timeout", type=int, default=10, help="command/network timeout in seconds")
    parser.add_argument("--language", choices=("zh", "en"), default="zh", help="report language")
    parser.add_argument("--verbose", action="store_true", help="retain diagnostic warnings")
    parser.add_argument("--mask", action="store_true", help="mask network identifiers and addresses")
    parser.add_argument("--json", metavar="PATH", help="write the complete JSON report")
    parser.add_argument("--csv", metavar="PATH", help="write the complete CSV report")
    return parser


def apply_quality(report, runner, public_test=True, run_speed=False, timeout=10):
    gateway = report.get("ip", "gateway")
    if gateway.available:
        result = ping_target(runner, str(gateway.value))
        if result:
            report.set("local_quality", "target", gateway.value, source="default gateway")
            report.set("local_quality", "reachable", result["reachable"], source="ping")
            report.set("local_quality", "packet_loss", result["packet_loss_percent"], "%", "ping")
            if result["latency_ms"] is not None: report.set("local_quality", "latency", result["latency_ms"], "ms", "ping")
            if result["jitter_ms"] is not None: report.set("local_quality", "jitter", result["jitter_ms"], "ms", "ping")
    else:
        report.mark_unavailable("local_quality", "target", "default gateway not available")
    if not public_test:
        for name in report.sections["public_quality"]: report.mark_unavailable("public_quality", name, "disabled by --no-public-test")
        return
    dns = dns_test()
    report.set("public_quality", "target", "1.1.1.1 / www.example.com", source="defaults")
    if dns.get("latency_ms") is None: report.mark_unavailable("public_quality", "dns_latency", dns.get("reason", "DNS failed"), "socket.getaddrinfo")
    else: report.set("public_quality", "dns_latency", dns["latency_ms"], "ms", "socket.getaddrinfo")
    public = ping_target(runner, "1.1.1.1")
    if public:
        report.set("public_quality", "reachable", public["reachable"], source="ping")
        report.set("public_quality", "packet_loss", public["packet_loss_percent"], "%", "ping")
        if public["latency_ms"] is not None: report.set("public_quality", "latency", public["latency_ms"], "ms", "ping")
        if public["jitter_ms"] is not None: report.set("public_quality", "jitter", public["jitter_ms"], "ms", "ping")
    if run_speed:
        speed = speed_test(timeout)
        if speed is None: report.mark_unavailable("public_quality", "download_speed", "download test failed", "Cloudflare 1 MB")
        else: report.set("public_quality", "download_speed", speed, "Mbps", "Cloudflare 1 MB")
    else: report.mark_unavailable("public_quality", "download_speed", "enable with --speedtest")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        runner = CommandRunner(timeout=max(1, args.timeout), verbose=args.verbose)
        report = collect_report(runner, args.interface)
        apply_quality(report, runner, not args.no_public_test, args.speedtest, args.timeout)
        report.diagnosis = diagnose(report)
        print(render_text(report, args.language, args.mask), end="")
        if args.json: _write(args.json, render_json(report, args.mask))
        if args.csv: _write(args.csv, render_csv(report, args.mask))
        return 0
    except RuntimeError as exc:
        print("Wi-Fi detector error: %s" % exc, file=sys.stderr)
        return 2


def _write(path, content):
    with open(path, "w", encoding="utf-8", newline="") as handle: handle.write(content)
