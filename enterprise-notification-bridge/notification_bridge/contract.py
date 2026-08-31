from __future__ import absolute_import

import copy
import hashlib
import json
from collections.abc import Mapping

from .models import Envelope


ZH_MARKDOWN_TITLE = "# 📶 Wi-Fi 健康报告"
ZH_MARKDOWN_SECTIONS = (
    "## ⭐ 核心参数", "## 🏠 本地网络质量", "## 🌐 公网质量", "## 🧭 诊断与建议",
)
ZH_MARKDOWN_SUBSECTIONS = ("### 主要问题", "### 优化建议")
ZH_CORE_ROW_LABELS = (
    "操作系统版本", "芯片架构", "MAC 地址", "Wi-Fi 名称", "无线接口",
    "Wi-Fi 工作频段", "无线信道", "信道频宽", "信号强度 RSSI", "信噪比 SNR",
    "发送速率", "接收速率", "网关延迟", "网关抖动", "网关丢包",
    "公网延迟", "公网丢包", "安全类型",
)
EN_MARKDOWN_TITLE = "# 📶 Wi-Fi Health Report"
EN_MARKDOWN_SECTIONS = (
    "## ⭐ Core Metrics", "## 🏠 Local Network Quality", "## 🌐 Public Network Quality",
    "## 🧭 Diagnostics & Recommendations",
)
EN_MARKDOWN_SUBSECTIONS = ("### Main Issues", "### Recommendations")
EN_CORE_ROW_LABELS = (
    "Operating System Version", "Chip Architecture", "MAC Address", "Wi-Fi Name",
    "Wireless Interface", "Wi-Fi Band", "Wireless Channel", "Channel Width",
    "Signal Strength (RSSI)", "Signal-to-Noise Ratio (SNR)", "Transmit Rate",
    "Receive Rate", "Gateway Latency", "Gateway Jitter", "Gateway Packet Loss",
    "Public Latency", "Public Packet Loss", "Security Type",
)
MARKDOWN_LAYOUTS = (
    (ZH_MARKDOWN_TITLE, ZH_MARKDOWN_SECTIONS, ZH_MARKDOWN_SUBSECTIONS, ZH_CORE_ROW_LABELS),
    (EN_MARKDOWN_TITLE, EN_MARKDOWN_SECTIONS, EN_MARKDOWN_SUBSECTIONS, EN_CORE_ROW_LABELS),
)
JSON_SECTIONS = (
    "system", "adapter", "connection", "radio", "link", "ip",
    "local_quality", "public_quality",
)
JSON_TOP_LEVEL_KEYS = ("schema_version", "sections", "diagnosis", "warnings")
FIELD_KEYS = ("value", "unit", "availability", "source", "reason")
SECTION_FIELDS = (
    ("system", ("os", "os_version", "build", "architecture", "checked_at", "privilege", "python_version")),
    ("adapter", ("interface", "description", "status", "mac", "driver", "firmware", "country_code", "supported_phy", "current_phy")),
    ("connection", ("ssid", "bssid", "state", "security", "authentication", "cipher", "band", "channel", "center_channel", "channel_width")),
    ("radio", ("rssi", "noise", "snr", "signal_percent", "signal_level", "same_channel_networks", "adjacent_channel_networks")),
    ("link", ("tx_rate", "rx_rate", "max_rate", "mcs", "nss", "guard_interval")),
    ("ip", ("ipv4", "ipv6", "subnet", "gateway", "dns_servers", "dhcp_enabled", "dhcp_lease")),
    ("local_quality", ("target", "reachable", "latency", "jitter", "packet_loss")),
    ("public_quality", ("target", "reachable", "dns_latency", "latency", "jitter", "packet_loss", "download_speed")),
)
DIAGNOSIS_KEYS = (
    "score", "confidence_percent", "verdict", "category_scores", "issues", "recommendations",
)


class ContractError(ValueError):
    pass


def compute_report_id(markdown, report_json):
    canonical_json = json.dumps(report_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = (markdown + "\n" + canonical_json).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_envelope(markdown, report_json, summary_text, summary_mode, detector_version):
    envelope = Envelope(
        compute_report_id(markdown, report_json),
        report_json["sections"]["system"]["checked_at"]["value"],
        {"name": "wifi-health-detector", "version": detector_version},
        {"markdown": markdown, "json": copy.deepcopy(report_json)},
        {"mode": summary_mode, "text": summary_text},
    )
    validate_envelope(envelope)
    return envelope


def validate_envelope(envelope):
    if envelope.schema_version != "1":
        raise ContractError("unsupported envelope schema")
    if compute_report_id(envelope.report["markdown"], envelope.report["json"]) != envelope.report_id:
        raise ContractError("report_id does not match report")
    validate_markdown_contract(envelope.report["markdown"])
    validate_json_contract(envelope.report["json"])


def validate_markdown_contract(markdown):
    if not isinstance(markdown, str):
        raise ContractError("standard report must be Markdown text")
    lines = markdown.splitlines()
    for title, sections, subsections, core_row_labels in MARKDOWN_LAYOUTS:
        if ( [line for line in lines if line.startswith("# ")] == [title]
                and [line for line in lines if line.startswith("## ")] == list(sections)
                and [line for line in lines if line.startswith("### ")] == list(subsections)):
            start = lines.index(sections[0])
            end = lines.index(sections[1])
            data_rows = [line for line in lines[start + 1:end] if line.startswith("|")][2:]
            labels = tuple(_markdown_row_label(row) for row in data_rows)
            if labels == core_row_labels:
                return
            raise ContractError("standard report core row contract violated")
    raise ContractError("standard report section contract violated")


def validate_json_contract(report_json):
    if not isinstance(report_json, Mapping):
        raise ContractError("report JSON must be an object")
    if tuple(report_json.keys()) != JSON_TOP_LEVEL_KEYS:
        raise ContractError("report JSON top-level contract violated")
    if report_json["schema_version"] != "2.0":
        raise ContractError("unsupported report schema")

    sections = report_json["sections"]
    if not isinstance(sections, Mapping) or tuple(sections.keys()) != JSON_SECTIONS:
        raise ContractError("report JSON sections contract violated")
    for section_name, field_names in SECTION_FIELDS:
        fields = sections[section_name]
        if not isinstance(fields, Mapping) or tuple(fields.keys()) != field_names:
            raise ContractError("report JSON section fields contract violated")
        for field in fields.values():
            _validate_field(field)

    diagnosis = report_json["diagnosis"]
    if not isinstance(diagnosis, Mapping) or tuple(diagnosis.keys()) != DIAGNOSIS_KEYS:
        raise ContractError("report JSON diagnosis contract violated")
    if not isinstance(diagnosis["category_scores"], Mapping):
        raise ContractError("report JSON diagnosis category scores must be an object")
    if not isinstance(diagnosis["issues"], list) or not isinstance(diagnosis["recommendations"], list):
        raise ContractError("report JSON diagnosis lists are invalid")
    if not isinstance(report_json["warnings"], list):
        raise ContractError("report JSON warnings must be a list")


def _markdown_row_label(row):
    cells = row.split("|")
    return cells[1].strip() if len(cells) >= 3 else ""


def _validate_field(field):
    if not isinstance(field, Mapping) or tuple(field.keys()) != FIELD_KEYS:
        raise ContractError("report JSON field shape contract violated")
    if not isinstance(field["unit"], str) or not isinstance(field["source"], str):
        raise ContractError("report JSON field text is invalid")
    if field["availability"] not in ("available", "unavailable"):
        raise ContractError("report JSON field availability is invalid")
    if not isinstance(field["reason"], str):
        raise ContractError("report JSON field reason is invalid")
    if field["availability"] == "unavailable" and (field["value"] is not None or not field["reason"]):
        raise ContractError("report JSON unavailable field is invalid")
