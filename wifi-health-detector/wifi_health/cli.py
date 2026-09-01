from __future__ import absolute_import, print_function

import argparse
import json
import statistics
import sys

from .collectors import collect_report
from .command import CommandRunner
from .diagnose import diagnose
from .network import dns_test, ping_target, speed_test
from .notification import trigger_notification
from .output import (
    render_csv,
    render_json,
    render_text,
    validate_standard_json,
    validate_standard_report,
)


PUBLIC_PING_TARGETS = ("223.5.5.5", "223.6.6.6", "119.29.29.29")
PUBLIC_DNS_HOSTS = ("www.baidu.com", "www.taobao.com")
PUBLIC_TARGET_LABEL = " / ".join(PUBLIC_PING_TARGETS + PUBLIC_DNS_HOSTS)


def build_parser():
    parser = argparse.ArgumentParser(description="Cross-platform Wi-Fi health detector")
    parser.add_argument("--interface", help="override the automatically detected Wi-Fi interface")
    parser.add_argument("--speedtest", action="store_true", help="run an optional 1 MB throughput test")
    parser.add_argument("--no-public-test", action="store_true", help="skip DNS and public connectivity tests")
    parser.add_argument("--timeout", type=int, default=10, help="command/network timeout in seconds")
    parser.add_argument("--language", choices=("zh", "en"), default="zh", help="report language")
    parser.add_argument("--view", choices=("summary",), default="summary", help="standard fixed report (the only Markdown view)")
    parser.add_argument("--verbose", action="store_true", help="retain diagnostic warnings")
    parser.add_argument("--mask", action="store_true", help="mask network identifiers and addresses")
    parser.add_argument("--json", metavar="PATH", help="write the complete JSON report")
    parser.add_argument("--csv", metavar="PATH", help="write the complete CSV report")
    parser.add_argument("--no-notify", action="store_true", help="skip enterprise notification delivery")
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
    report.set("public_quality", "target", PUBLIC_TARGET_LABEL, source="mainland China defaults")
    dns_results = [dns_test(host) for host in PUBLIC_DNS_HOSTS]
    dns_latencies = [item["latency_ms"] for item in dns_results if item.get("latency_ms") is not None]
    if dns_latencies:
        report.set("public_quality", "dns_latency", _median(dns_latencies), "ms", "socket.getaddrinfo: Baidu/Taobao")
    else:
        reasons = [item.get("reason") for item in dns_results if item.get("reason")]
        report.mark_unavailable("public_quality", "dns_latency", "; ".join(reasons) or "DNS failed", "socket.getaddrinfo")

    ping_results = [ping_target(runner, target) for target in PUBLIC_PING_TARGETS]
    ping_results = [item for item in ping_results if item]
    reachable_results = [item for item in ping_results if item.get("reachable")]
    report.set("public_quality", "reachable", bool(reachable_results), source="multi-target ping")
    if ping_results:
        report.set("public_quality", "packet_loss", _median([item["packet_loss_percent"] for item in ping_results]), "%", "multi-target ping median")
    latencies = [item["latency_ms"] for item in reachable_results if item.get("latency_ms") is not None]
    jitters = [item["jitter_ms"] for item in reachable_results if item.get("jitter_ms") is not None]
    if latencies: report.set("public_quality", "latency", _median(latencies), "ms", "multi-target ping median")
    if jitters: report.set("public_quality", "jitter", _median(jitters), "ms", "multi-target ping median")
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
        markdown = render_text(report, args.language, args.mask, args.view)
        validate_standard_report(markdown, args.language)
        json_text = render_json(report, args.mask)
        report_json = json.loads(json_text)
        validate_standard_json(report_json)
        print(markdown, end="")
        if args.json: _write(args.json, json_text)
        if args.csv: _write(args.csv, render_csv(report, args.mask))
        if not args.no_notify:
            notification_result = trigger_notification(markdown, report_json)
            if notification_result.requires_attention:
                print(notification_result.message, file=sys.stderr)
        return 0
    except RuntimeError as exc:
        print("Wi-Fi detector error: %s" % exc, file=sys.stderr)
        return 2


def _write(path, content):
    with open(path, "w", encoding="utf-8", newline="") as handle: handle.write(content)


def _median(values):
    return round(float(statistics.median(values)), 3)
