from __future__ import absolute_import

import copy
from datetime import datetime
import hashlib
import json
import re
from collections.abc import Mapping

from .models import Envelope
from .standard_report import detect_language, normalize_markdown, render_standard_markdown


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
ZH_LOCAL_ROW_LABELS = ("测试目标", "可达状态", "平均延迟", "网络抖动", "丢包率")
EN_LOCAL_ROW_LABELS = ("Target", "Reachable", "Latency", "Jitter", "Packet Loss")
ZH_PUBLIC_ROW_LABELS = (
    "测试目标", "可达状态", "DNS 解析延迟", "平均延迟", "网络抖动", "丢包率", "下载速度",
)
EN_PUBLIC_ROW_LABELS = (
    "Target", "Reachable", "DNS Latency", "Latency", "Jitter", "Packet Loss",
    "Download Speed",
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
CATEGORY_KEYS = ("signal", "interference", "link", "local", "public", "security")
RECOMMENDATION_KEYS = ("id", "priority", "reason", "action")
ISSUE_IDS = frozenset((
    "weak_signal", "moderate_signal", "channel_congestion", "gateway_loss",
    "upstream_loss", "slow_dns", "weak_security",
))
RECOMMENDATION_IDS = ISSUE_IDS | frozenset(("prefer_higher_band", "no_action"))
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
DETECTOR_VERSION_PATTERN = re.compile(r"^2\.(?:4|5)\.\d+(?:[+-][0-9A-Za-z.-]+)?$")
REPORT_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    pass


def compute_report_id(markdown, report_json):
    canonical_json = json.dumps(report_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = (markdown + "\n" + canonical_json).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_envelope(markdown, report_json, summary_text, summary_mode, detector_version):
    if isinstance(markdown, str):
        markdown = normalize_markdown(markdown)
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
    _validate_generated_at(envelope.generated_at)
    _validate_detector(envelope.detector)
    _validate_ai_summary(envelope.ai_summary)
    report = envelope.report
    if not isinstance(report, Mapping) or set(report) != set(("markdown", "json")):
        raise ContractError("report must contain markdown and json")
    if (not isinstance(envelope.report_id, str)
            or not REPORT_ID_PATTERN.match(envelope.report_id)):
        raise ContractError("report_id must be a SHA-256 identifier")
    if compute_report_id(report["markdown"], report["json"]) != envelope.report_id:
        raise ContractError("report_id does not match report")
    validate_markdown_contract(report["markdown"])
    validate_json_contract(report["json"])
    language = detect_language(report["markdown"])
    if (language is None
            or render_standard_markdown(report["json"], language) != report["markdown"]):
        raise ContractError("standard report canonical Markdown contract violated")
    checked_at = report["json"]["sections"]["system"]["checked_at"]["value"]
    if checked_at != envelope.generated_at:
        raise ContractError("generated_at does not match report")


def validate_markdown_contract(markdown):
    if not isinstance(markdown, str):
        raise ContractError("standard report must be Markdown text")
    lines = markdown.splitlines()
    if markdown.startswith(ZH_MARKDOWN_TITLE + "\n"):
        title = ZH_MARKDOWN_TITLE
        sections = ZH_MARKDOWN_SECTIONS
        subsections = ZH_MARKDOWN_SUBSECTIONS
        summary_headers = ("健康状态", "健康评分", "数据置信度")
        core_headers = ("核心参数", "当前值")
        quality_headers = ("参数", "当前值", "状态")
        core_rows = ZH_CORE_ROW_LABELS
        local_rows = ZH_LOCAL_ROW_LABELS
        public_rows = ZH_PUBLIC_ROW_LABELS
    elif markdown.startswith(EN_MARKDOWN_TITLE + "\n"):
        title = EN_MARKDOWN_TITLE
        sections = EN_MARKDOWN_SECTIONS
        subsections = EN_MARKDOWN_SUBSECTIONS
        summary_headers = ("Health", "Score", "Data Confidence")
        core_headers = ("Metric", "Current Value")
        quality_headers = ("Parameter", "Current Value", "Status")
        core_rows = EN_CORE_ROW_LABELS
        local_rows = EN_LOCAL_ROW_LABELS
        public_rows = EN_PUBLIC_ROW_LABELS
    else:
        raise ContractError("standard report title contract violated")

    if [line for line in lines if line.startswith("# ")] != [title]:
        raise ContractError("standard report title contract violated")
    if [line for line in lines if line.startswith("## ")] != list(sections):
        raise ContractError("standard report section contract violated")
    if [line for line in lines if line.startswith("### ")] != list(subsections):
        raise ContractError("standard report subsection contract violated")

    table_specs = (
        (lines[:lines.index(sections[0])], summary_headers,
         (":---:", ":---:", ":---:"), None, 1, "summary"),
        (_section_block(lines, sections[0], sections[1]), core_headers,
         ("---", "---"), core_rows, 18, "core"),
        (_section_block(lines, sections[1], sections[2]), quality_headers,
         ("---", "---", ":---:"), local_rows, 5, "local quality"),
        (_section_block(lines, sections[2], sections[3]), quality_headers,
         ("---", "---", ":---:"), public_rows, 7, "public quality"),
    )
    for block, headers, separators, row_labels, row_count, table_name in table_specs:
        _validate_fixed_table(
            block, headers, separators, row_labels, row_count, table_name
        )


def validate_json_contract(report_json):
    if not isinstance(report_json, Mapping):
        raise ContractError("report JSON must be an object")
    if set(report_json) != set(JSON_TOP_LEVEL_KEYS):
        raise ContractError("report JSON top-level contract violated")
    if report_json["schema_version"] != "2.0":
        raise ContractError("unsupported report schema")

    sections = report_json["sections"]
    if not isinstance(sections, Mapping) or set(sections) != set(JSON_SECTIONS):
        raise ContractError("report JSON sections contract violated")
    for section_name, field_names in SECTION_FIELDS:
        fields = sections[section_name]
        if not isinstance(fields, Mapping) or set(fields) != set(field_names):
            raise ContractError("report JSON section fields contract violated")
        for field in fields.values():
            _validate_field(field)

    diagnosis = report_json["diagnosis"]
    if not isinstance(diagnosis, Mapping) or set(diagnosis) != set(DIAGNOSIS_KEYS):
        raise ContractError("report JSON diagnosis contract violated")
    _validate_score(diagnosis["score"], "score")
    _validate_score(diagnosis["confidence_percent"], "confidence")
    if diagnosis["verdict"] not in ("healthy", "warning", "poor", "insufficient_data"):
        raise ContractError("report JSON diagnosis verdict is invalid")
    category_scores = diagnosis["category_scores"]
    if (not isinstance(category_scores, Mapping)
            or set(category_scores) != set(CATEGORY_KEYS)):
        raise ContractError("report JSON diagnosis category scores are invalid")
    for score in category_scores.values():
        _validate_score(score, "category score")
    if not isinstance(diagnosis["issues"], list) or not isinstance(diagnosis["recommendations"], list):
        raise ContractError("report JSON diagnosis lists are invalid")
    if any(not isinstance(item, str) or item not in ISSUE_IDS
           for item in diagnosis["issues"]):
        raise ContractError("report JSON diagnosis issue is invalid")
    for item in diagnosis["recommendations"]:
        _validate_recommendation(item)
    if not isinstance(report_json["warnings"], list):
        raise ContractError("report JSON warnings must be a list")
    if any(not _non_empty_string(item) for item in report_json["warnings"]):
        raise ContractError("report JSON warning is invalid")


def _section_block(lines, start, end):
    return lines[lines.index(start) + 1:lines.index(end)]


def _validate_fixed_table(block, headers, separators, row_labels, row_count, name):
    table_lines = [line for line in block if line.startswith("|")]
    if len(table_lines) != row_count + 2:
        raise ContractError(
            "standard report {0} table row contract violated".format(name)
        )
    expected_headers = tuple(" " + value + " " for value in headers)
    expected_separators = tuple(" " + value + " " for value in separators)
    if _markdown_cells(table_lines[0]) != expected_headers:
        raise ContractError(
            "standard report {0} table header contract violated".format(name)
        )
    if _markdown_cells(table_lines[1]) != expected_separators:
        raise ContractError(
            "standard report {0} table separator contract violated".format(name)
        )
    data_rows = [_markdown_cells(row) for row in table_lines[2:]]
    if any(len(row) != len(headers) for row in data_rows):
        raise ContractError(
            "standard report {0} column contract violated".format(name)
        )
    if row_labels is not None:
        labels = tuple(row[0] for row in data_rows)
        expected_labels = tuple(" " + value + " " for value in row_labels)
        if labels != expected_labels:
            raise ContractError(
                "standard report {0} row contract violated".format(name)
            )


def _markdown_cells(row):
    if not row.startswith("|") or not row.endswith("|"):
        return ()
    cells = [""]
    index = 1
    end = len(row) - 1
    while index < end:
        character = row[index]
        if character == "\\" and index + 1 < end and row[index + 1] == "|":
            cells[-1] += "|"
            index += 2
            continue
        if character == "|":
            cells.append("")
        else:
            cells[-1] += character
        index += 1
    return tuple(cells)


def _validate_generated_at(value):
    if not isinstance(value, str) or not value or not RFC3339_PATTERN.match(value):
        raise ContractError("generated_at must be an RFC3339 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    formats = ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z")
    for timestamp_format in formats:
        try:
            datetime.strptime(normalized, timestamp_format)
            return
        except ValueError:
            pass
    raise ContractError("generated_at must be an RFC3339 string")


def _validate_detector(value):
    if (not isinstance(value, Mapping) or set(value) != set(("name", "version"))
            or value.get("name") != "wifi-health-detector"
            or not isinstance(value.get("version"), str)
            or not DETECTOR_VERSION_PATTERN.match(value["version"])):
        raise ContractError("detector identity or version is unsupported")


def _validate_ai_summary(value):
    if (not isinstance(value, Mapping) or set(value) != set(("mode", "text"))
            or value["mode"] not in ("host_agent", "deterministic")
            or not isinstance(value["text"], str)):
        raise ContractError("ai_summary must contain a supported mode and text string")


def _non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_field(field):
    if not isinstance(field, Mapping) or set(field) != set(FIELD_KEYS):
        raise ContractError("report JSON field shape contract violated")
    if not isinstance(field["unit"], str) or not isinstance(field["source"], str):
        raise ContractError("report JSON field text is invalid")
    if field["availability"] not in ("available", "unavailable"):
        raise ContractError("report JSON field availability is invalid")
    if not isinstance(field["reason"], str):
        raise ContractError("report JSON field reason is invalid")
    if field["availability"] == "available" and field["value"] is None:
        raise ContractError("report JSON available field is invalid")
    if field["availability"] == "unavailable" and (field["value"] is not None or not field["reason"]):
        raise ContractError("report JSON unavailable field is invalid")


def _validate_score(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("report JSON diagnosis {0} is invalid".format(label))
    if value < 0 or value > 100:
        raise ContractError("report JSON diagnosis {0} is invalid".format(label))


def _validate_recommendation(value):
    if not isinstance(value, Mapping) or set(value) != set(RECOMMENDATION_KEYS):
        raise ContractError("report JSON diagnosis recommendation is invalid")
    if value["id"] not in RECOMMENDATION_IDS:
        raise ContractError("report JSON diagnosis recommendation is invalid")
    if value["priority"] not in ("high", "medium", "low"):
        raise ContractError("report JSON diagnosis recommendation is invalid")
    if not _non_empty_string(value["reason"]) or not _non_empty_string(value["action"]):
        raise ContractError("report JSON diagnosis recommendation is invalid")
