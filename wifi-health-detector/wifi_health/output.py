from __future__ import absolute_import

import csv
import io
import json
import re
from collections.abc import Mapping

from .models import SECTION_FIELDS


SECTION_LABELS = {
    "zh": {"system": "系统", "adapter": "无线适配器", "connection": "Wi-Fi 连接", "radio": "射频", "link": "链路", "ip": "IP 网络", "local_quality": "本地网络质量", "public_quality": "公网质量"},
    "en": {"system": "System", "adapter": "Wireless Adapter", "connection": "Wi-Fi Connection", "radio": "Radio", "link": "Link", "ip": "IP Network", "local_quality": "Local Network Quality", "public_quality": "Public Network Quality"},
}

FIELD_LABELS_ZH = {
    "os": "操作系统", "os_version": "系统版本", "build": "系统构建", "architecture": "架构", "checked_at": "检测时间", "privilege": "运行权限", "python_version": "Python 版本",
    "interface": "无线接口", "description": "适配器描述", "status": "适配器状态", "mac": "MAC 地址", "driver": "驱动版本", "firmware": "固件版本", "country_code": "国家/地区码", "supported_phy": "支持的 PHY", "current_phy": "当前 PHY",
    "ssid": "Wi-Fi 名称", "bssid": "接入点 BSSID", "state": "连接状态", "security": "安全类型", "authentication": "认证方式", "cipher": "加密算法", "band": "工作频段", "channel": "无线信道", "center_channel": "中心信道", "channel_width": "信道频宽",
    "rssi": "信号强度 RSSI", "noise": "噪声", "snr": "信噪比 SNR", "signal_percent": "信号百分比", "signal_level": "信号等级", "same_channel_networks": "同信道网络数", "adjacent_channel_networks": "邻信道网络数",
    "tx_rate": "发送协商速率", "rx_rate": "接收协商速率", "max_rate": "最大速率", "mcs": "MCS", "nss": "空间流 NSS", "guard_interval": "保护间隔",
    "ipv4": "IPv4 地址", "ipv6": "IPv6 地址", "subnet": "子网掩码", "gateway": "默认网关", "dns_servers": "DNS 服务器", "dhcp_enabled": "DHCP 状态", "dhcp_lease": "DHCP 租约",
    "target": "测试目标", "reachable": "可达状态", "latency": "平均延迟", "jitter": "网络抖动", "packet_loss": "丢包率", "dns_latency": "DNS 解析延迟", "download_speed": "下载速度",
}
FIELD_LABELS_EN = {name: name.replace("_", " ").title() for name in FIELD_LABELS_ZH}
FIELD_LABELS_EN.update({"ssid": "Wi-Fi Name (SSID)", "bssid": "Access Point BSSID", "rssi": "Signal (RSSI)", "snr": "Signal-to-Noise Ratio (SNR)", "tx_rate": "Transmit Link Rate", "rx_rate": "Receive Link Rate", "dns_latency": "DNS Latency", "dns_servers": "DNS Servers", "ipv4": "IPv4 Address", "ipv6": "IPv6 Address", "dhcp_enabled": "DHCP Status", "dhcp_lease": "DHCP Lease"})

SENSITIVE_FIELDS = {"ssid", "bssid", "mac", "ipv4", "ipv6", "gateway", "dns_servers"}
ZH_RECOMMENDATIONS = {
    "weak_signal": "靠近接入点、减少遮挡，或增加更近的 Mesh/AP 节点。", "moderate_signal": "优化 AP 位置或减少遮挡，以改善视频会议和游戏体验。", "channel_congestion": "启用自动信道选择，或选择较空闲的不重叠信道。", "prefer_higher_band": "覆盖足够时优先使用 5 GHz 或 6 GHz；2.4 GHz 留给远距离和旧设备。", "gateway_loss": "先靠近路由器复测，再检查干扰、AP 负载、固件和 Mesh 回程。", "upstream_loss": "优先检查运营商或上游链路，不要先修改 Wi-Fi 设置。", "slow_dns": "重复测试 DNS，并比较路由器/运营商 DNS 与可信公共 DNS。", "weak_security": "启用 WPA2-AES 或 WPA3，并设置高强度密码。", "no_action": "当前无需调整 Wi-Fi。",
}
ZH_ISSUES = {"weak_signal": "Wi-Fi 信号较弱", "moderate_signal": "Wi-Fi 信号需要关注", "channel_congestion": "当前信道较拥挤", "gateway_loss": "本地网关存在丢包", "upstream_loss": "公网链路存在丢包", "slow_dns": "DNS 解析较慢", "weak_security": "无线安全配置较弱"}
EN_ISSUES = {"weak_signal": "Weak Wi-Fi signal", "moderate_signal": "Wi-Fi signal needs attention", "channel_congestion": "Channel congestion", "gateway_loss": "Packet loss to the gateway", "upstream_loss": "Packet loss on the public path", "slow_dns": "Slow DNS resolution", "weak_security": "Weak wireless security"}
BADGES = {
    "zh": {"healthy": "✅ 健康", "warning": "⚠️ 一般/需关注", "poor": "❌ 较差", "insufficient_data": "❔ 数据不足"},
    "en": {"healthy": "✅ Healthy", "warning": "⚠️ Warning", "poor": "❌ Poor", "insufficient_data": "❔ Insufficient data"},
}
REASON_ZH = {"not provided by operating system": "操作系统未提供", "not found": "未找到", "permission denied": "权限不足", "unsupported": "当前系统不支持", "default gateway not available": "默认网关不可用", "disabled by --no-public-test": "已通过 --no-public-test 禁用", "enable with --speedtest": "使用 --speedtest 开启", "download test failed": "下载测速失败", "macOS does not expose the current receive PHY rate": "macOS 未提供当前接收 PHY 速率"}
JSON_TOP_LEVEL_KEYS = ("schema_version", "sections", "diagnosis", "warnings")
FIELD_KEYS = ("value", "unit", "availability", "source", "reason")
DIAGNOSIS_KEYS = (
    "score", "confidence_percent", "verdict", "category_scores", "issues",
    "recommendations",
)
CATEGORY_KEYS = ("signal", "interference", "link", "local", "public", "security")
RECOMMENDATION_KEYS = ("id", "priority", "reason", "action")
ISSUE_IDS = frozenset((
    "weak_signal", "moderate_signal", "channel_congestion", "gateway_loss",
    "upstream_loss", "slow_dns", "weak_security",
))
RECOMMENDATION_IDS = ISSUE_IDS | frozenset(("prefer_higher_band", "no_action"))
ZH_CORE_ROW_LABELS = (
    "操作系统版本", "芯片架构", "MAC 地址", "Wi-Fi 名称", "无线接口",
    "Wi-Fi 工作频段", "无线信道", "信道频宽", "信号强度 RSSI", "信噪比 SNR",
    "发送速率", "接收速率", "网关延迟", "网关抖动", "网关丢包",
    "公网延迟", "公网丢包", "安全类型",
)
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


class ReportContractError(RuntimeError):
    pass


def _masked(name, value):
    if value is None: return value
    text = str(value)
    if name == "ssid": return "***"
    if name in ("mac", "bssid"):
        parts = re.split("[:-]", text)
        return ":".join(parts[:2] + ["**", "**"] + parts[-2:]) if len(parts) == 6 else "***"
    if name in ("ipv4", "gateway"):
        parts = text.split(".")
        if len(parts) == 4: return ".".join(parts[:2] + ["***", parts[-1]])
    if name == "ipv6": return text.split(":", 2)[0] + ":***"
    if name == "dns_servers": return "***"
    return text


def flatten_report(report, mask=False):
    rows = []
    for section, fields in report.sections.items():
        for name, item in fields.items():
            value = _masked(name, item.value) if mask and name in SENSITIVE_FIELDS else item.value
            rows.append({"section": section, "field": name, "value": "" if value is None else value, "unit": item.unit, "availability": item.availability, "source": item.source, "reason": item.reason})
    return rows


def _masked_dict(report, mask):
    payload = report.to_dict()
    if mask:
        for fields in payload["sections"].values():
            for name, item in fields.items():
                if name in SENSITIVE_FIELDS: item["value"] = _masked(name, item["value"])
    return payload


def render_json(report, mask=False):
    return json.dumps(_masked_dict(report, mask), ensure_ascii=False, indent=2)


def validate_standard_json(report_json):
    if not isinstance(report_json, Mapping):
        raise ReportContractError("standard report JSON must be an object")
    if set(report_json) != set(JSON_TOP_LEVEL_KEYS):
        raise ReportContractError("standard report JSON top-level contract violated")
    if report_json["schema_version"] != "2.0":
        raise ReportContractError("unsupported standard report JSON schema")

    sections = report_json["sections"]
    if not isinstance(sections, Mapping) or set(sections) != set(SECTION_FIELDS):
        raise ReportContractError("standard report JSON sections contract violated")
    for section_name, field_names in SECTION_FIELDS.items():
        fields = sections[section_name]
        if not isinstance(fields, Mapping) or set(fields) != set(field_names):
            raise ReportContractError("standard report JSON section fields contract violated")
        for field in fields.values():
            _validate_standard_field(field)

    diagnosis = report_json["diagnosis"]
    if not isinstance(diagnosis, Mapping) or set(diagnosis) != set(DIAGNOSIS_KEYS):
        raise ReportContractError("standard report JSON diagnosis contract violated")
    _validate_score(diagnosis["score"], "score")
    _validate_score(diagnosis["confidence_percent"], "confidence")
    if diagnosis["verdict"] not in ("healthy", "warning", "poor", "insufficient_data"):
        raise ReportContractError("standard report JSON verdict is invalid")
    category_scores = diagnosis["category_scores"]
    if (not isinstance(category_scores, Mapping)
            or set(category_scores) != set(CATEGORY_KEYS)):
        raise ReportContractError("standard report JSON category scores are invalid")
    for score in category_scores.values():
        _validate_score(score, "category score")
    if not isinstance(diagnosis["issues"], list) or not isinstance(diagnosis["recommendations"], list):
        raise ReportContractError("standard report JSON diagnosis lists are invalid")
    if any(not isinstance(item, str) or item not in ISSUE_IDS
           for item in diagnosis["issues"]):
        raise ReportContractError("standard report JSON diagnosis issue is invalid")
    for item in diagnosis["recommendations"]:
        _validate_recommendation(item)
    if not isinstance(report_json["warnings"], list):
        raise ReportContractError("standard report JSON warnings must be a list")
    if any(not isinstance(item, str) or not item.strip()
           for item in report_json["warnings"]):
        raise ReportContractError("standard report JSON warning is invalid")


def _validate_standard_field(field):
    if not isinstance(field, Mapping) or set(field) != set(FIELD_KEYS):
        raise ReportContractError("standard report JSON field contract violated")
    if not isinstance(field["unit"], str) or not isinstance(field["source"], str):
        raise ReportContractError("standard report JSON field text is invalid")
    if field["availability"] not in ("available", "unavailable"):
        raise ReportContractError("standard report JSON field availability is invalid")
    if not isinstance(field["reason"], str):
        raise ReportContractError("standard report JSON field reason is invalid")
    if field["availability"] == "available" and field["value"] is None:
        raise ReportContractError("standard report JSON available field is invalid")
    if field["availability"] == "unavailable" and (
            field["value"] is not None or not field["reason"]):
        raise ReportContractError("standard report JSON unavailable field is invalid")


def _validate_score(value, label):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or value < 0 or value > 100):
        raise ReportContractError(
            "standard report JSON {0} is invalid".format(label)
        )


def _validate_recommendation(value):
    if not isinstance(value, Mapping) or set(value) != set(RECOMMENDATION_KEYS):
        raise ReportContractError("standard report JSON recommendation is invalid")
    if value["id"] not in RECOMMENDATION_IDS:
        raise ReportContractError("standard report JSON recommendation is invalid")
    if value["priority"] not in ("high", "medium", "low"):
        raise ReportContractError("standard report JSON recommendation is invalid")
    if (not isinstance(value["reason"], str) or not value["reason"].strip()
            or not isinstance(value["action"], str) or not value["action"].strip()):
        raise ReportContractError("standard report JSON recommendation is invalid")


def render_csv(report, mask=False):
    stream = io.StringIO(); names = ["section", "field", "value", "unit", "availability", "source", "reason"]
    writer = csv.DictWriter(stream, fieldnames=names); writer.writeheader(); writer.writerows(flatten_report(report, mask))
    return stream.getvalue()


def _escape(value):
    if isinstance(value, float) and value.is_integer(): value = int(value)
    if isinstance(value, (list, tuple)): value = ", ".join(str(part) for part in value)
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


def _reason(reason, language):
    return REASON_ZH.get(reason, reason or "原因未知") if language == "zh" else (reason or "reason unknown")


def _display_field(report, section, name, language, mask=False, include_unit=True):
    item = report.get(section, name)
    if not item.available:
        return "—（系统未提供：%s）" % _reason(item.reason, language) if language == "zh" else "— (Unavailable: %s)" % _reason(item.reason, language)
    value = _masked(name, item.value) if mask and name in SENSITIVE_FIELDS else item.value
    if isinstance(value, bool): value = ("是" if value else "否") if language == "zh" else ("Yes" if value else "No")
    shown = _escape(value)
    return shown + (" " + item.unit if include_unit and item.unit else "")


def _localized_evidence(item, language):
    if language != "zh": return item["reason"]
    reason = item["reason"]; identifier = item["id"]
    number = re.search(r"-?[\d.]+", reason)
    value = number.group(0) if number else "—"
    templates = {
        "weak_signal": "RSSI 为 %s dBm", "moderate_signal": "RSSI 为 %s dBm",
        "channel_congestion": "当前信道附近检测到 %s 个同信道网络",
        "gateway_loss": "网关丢包率为 %s%%", "slow_dns": "DNS 解析耗时 %s ms",
        "upstream_loss": "本地网关稳定，但公网链路丢包偏高",
        "weak_security": "检测到开放或已过时的 Wi-Fi 安全配置",
        "no_action": "未发现需要处理的明显问题",
    }
    template = templates.get(identifier)
    return (template % value) if template and "%s" in template else (template or reason)


def _core_rows(report, language, mask):
    labels = ZH_CORE_ROW_LABELS if language == "zh" else EN_CORE_ROW_LABELS
    operating_system = "%s %s" % (
        _display_field(report, "system", "os", language, mask),
        _display_field(report, "system", "os_version", language, mask),
    )
    values = [
        operating_system,
        _display_field(report, "system", "architecture", language, mask),
        _display_field(report, "adapter", "mac", language, mask),
        _display_field(report, "connection", "ssid", language, mask),
        _display_field(report, "adapter", "interface", language, mask),
        _display_field(report, "connection", "band", language, mask),
        _display_field(report, "connection", "channel", language, mask),
        _display_field(report, "connection", "channel_width", language, mask),
        _display_field(report, "radio", "rssi", language, mask), _display_field(report, "radio", "snr", language, mask),
        _display_field(report, "link", "tx_rate", language, mask),
        _display_field(report, "link", "rx_rate", language, mask),
        _display_field(report, "local_quality", "latency", language, mask),
        _display_field(report, "local_quality", "jitter", language, mask),
        _display_field(report, "local_quality", "packet_loss", language, mask),
        _display_field(report, "public_quality", "latency", language, mask),
        _display_field(report, "public_quality", "packet_loss", language, mask),
        _display_field(report, "connection", "security", language, mask),
    ]
    return list(zip(labels, values))


def _render_quality_sections(report, language, mask):
    zh = language == "zh"; field_labels = FIELD_LABELS_ZH if zh else FIELD_LABELS_EN
    sections = (
        ("local_quality", "## 🏠 " + ("本地网络质量" if zh else "Local Network Quality"), ("target", "reachable", "latency", "jitter", "packet_loss")),
        ("public_quality", "## 🌐 " + ("公网质量" if zh else "Public Network Quality"), ("target", "reachable", "dns_latency", "latency", "jitter", "packet_loss", "download_speed")),
    )
    headers = ("参数", "当前值", "状态") if zh else ("Parameter", "Current Value", "Status")
    lines = []
    for section, heading, names in sections:
        lines.extend(["", heading, "", "| %s | %s | %s |" % headers, "| --- | --- | :---: |"])
        for name in names:
            item = report.get(section, name)
            status = ("可用" if item.available else "不可用") if zh else ("Available" if item.available else "Unavailable")
            lines.append("| %s | %s | %s |" % (field_labels[name], _display_field(report, section, name, language, mask), status))
    return lines


def _render_dashboard(report, language, mask):
    zh = language == "zh"; diagnosis = report.diagnosis or {}
    title = "# 📶 Wi-Fi 健康报告" if zh else "# 📶 Wi-Fi Health Report"
    metadata = "%s: %s　|　%s: %s　|　%s: %s" % (("检测时间" if zh else "Checked"), _display_field(report, "system", "checked_at", language, mask), ("系统" if zh else "System"), _display_field(report, "system", "os", language, mask), ("接口" if zh else "Interface"), _display_field(report, "adapter", "interface", language, mask))
    verdict = diagnosis.get("verdict", "insufficient_data"); badge = BADGES[language].get(verdict, BADGES[language]["insufficient_data"])
    status_headers = ("健康状态", "健康评分", "数据置信度") if zh else ("Health", "Score", "Data Confidence")
    core_headers = ("核心参数", "当前值") if zh else ("Metric", "Current Value")
    lines = [title, "", "> " + metadata, "", "| %s | %s | %s |" % status_headers, "| :---: | :---: | :---: |", "| %s | **%s/100** | **%s%%** |" % (badge, diagnosis.get("score", "—"), diagnosis.get("confidence_percent", 0)), "", "## ⭐ " + ("核心参数" if zh else "Core Metrics"), "", "| %s | %s |" % core_headers, "| --- | --- |"]
    lines.extend("| %s | %s |" % row for row in _core_rows(report, language, mask))
    lines.extend(_render_quality_sections(report, language, mask))
    lines.extend(["", "## 🧭 " + ("诊断与建议" if zh else "Diagnostics & Recommendations"), "", "### " + ("主要问题" if zh else "Main Issues"), ""])
    issues = diagnosis.get("issues", []); issue_labels = ZH_ISSUES if zh else EN_ISSUES
    lines.extend(("- %s" % issue_labels.get(item, item) for item in issues) if issues else ["- 未发现明确问题" if zh else "- No specific issue was identified"])
    lines.extend(["", "### " + ("优化建议" if zh else "Recommendations"), ""])
    recommendations = diagnosis.get("recommendations", [])
    if not recommendations: lines.append("- 暂无建议" if zh else "- No recommendation")
    for index, item in enumerate(recommendations, 1):
        priority = {"high": "高", "medium": "中", "low": "低"}.get(item["priority"], item["priority"]) if zh else item["priority"].title()
        action = ZH_RECOMMENDATIONS.get(item["id"], item["action"]) if zh else item["action"]
        lines.append("%d. **[%s]** %s — %s" % (index, priority, _escape(_localized_evidence(item, language)), _escape(action)))
    return lines


def render_text(report, language="zh", mask=False, view="summary"):
    language = language if language in SECTION_LABELS else "zh"
    lines = _render_dashboard(report, language, mask)
    text = "\n".join(lines) + "\n"
    validate_standard_report(text, language)
    return text


def validate_standard_report(text, language):
    if not isinstance(text, str):
        raise ReportContractError("standard report must be Markdown text")
    if language not in SECTION_LABELS:
        raise ReportContractError("standard report language is invalid")
    zh = language == "zh"
    expected_title = "# 📶 Wi-Fi 健康报告" if zh else "# 📶 Wi-Fi Health Report"
    expected_sections = [
        "## ⭐ " + ("核心参数" if zh else "Core Metrics"),
        "## 🏠 " + ("本地网络质量" if zh else "Local Network Quality"),
        "## 🌐 " + ("公网质量" if zh else "Public Network Quality"),
        "## 🧭 " + ("诊断与建议" if zh else "Diagnostics & Recommendations"),
    ]
    expected_subsections = [
        "### " + ("主要问题" if zh else "Main Issues"),
        "### " + ("优化建议" if zh else "Recommendations"),
    ]
    lines = text.splitlines()
    if [line for line in lines if line.startswith("# ")] != [expected_title]:
        raise ReportContractError("standard report title contract violated")
    if [line for line in lines if line.startswith("## ")] != expected_sections:
        raise ReportContractError("standard report section contract violated")
    if [line for line in lines if line.startswith("### ")] != expected_subsections:
        raise ReportContractError("standard report subsection contract violated")
    summary_headers = (
        ("健康状态", "健康评分", "数据置信度") if zh
        else ("Health", "Score", "Data Confidence")
    )
    metric_headers = ("核心参数", "当前值") if zh else ("Metric", "Current Value")
    quality_headers = ("参数", "当前值", "状态") if zh else (
        "Parameter", "Current Value", "Status"
    )
    table_specs = (
        (
            lines[:lines.index(expected_sections[0])], summary_headers,
            (":---:", ":---:", ":---:"), None, 1, "summary",
        ),
        (
            _section_block(lines, expected_sections[0], expected_sections[1]),
            metric_headers, ("---", "---"),
            ZH_CORE_ROW_LABELS if zh else EN_CORE_ROW_LABELS, 18, "core",
        ),
        (
            _section_block(lines, expected_sections[1], expected_sections[2]),
            quality_headers, ("---", "---", ":---:"),
            ZH_LOCAL_ROW_LABELS if zh else EN_LOCAL_ROW_LABELS, 5, "local quality",
        ),
        (
            _section_block(lines, expected_sections[2], expected_sections[3]),
            quality_headers, ("---", "---", ":---:"),
            ZH_PUBLIC_ROW_LABELS if zh else EN_PUBLIC_ROW_LABELS, 7, "public quality",
        ),
    )
    for block, headers, separators, row_labels, row_count, table_name in table_specs:
        _validate_fixed_table(
            block, headers, separators, row_labels, row_count, table_name
        )


def _section_block(lines, start, end):
    return lines[lines.index(start) + 1:lines.index(end)]


def _validate_fixed_table(block, headers, separators, row_labels, row_count, name):
    table_lines = [line for line in block if line.startswith("|")]
    if len(table_lines) != row_count + 2:
        raise ReportContractError(
            "standard report {0} table row contract violated".format(name)
        )
    expected_headers = tuple(" " + value + " " for value in headers)
    expected_separators = tuple(" " + value + " " for value in separators)
    if _markdown_cells(table_lines[0]) != expected_headers:
        raise ReportContractError(
            "standard report {0} table header contract violated".format(name)
        )
    if _markdown_cells(table_lines[1]) != expected_separators:
        raise ReportContractError(
            "standard report {0} table separator contract violated".format(name)
        )
    data_rows = [_markdown_cells(row) for row in table_lines[2:]]
    if any(len(row) != len(headers) for row in data_rows):
        raise ReportContractError(
            "standard report {0} column contract violated".format(name)
        )
    if row_labels is not None:
        labels = tuple(row[0] for row in data_rows)
        expected_labels = tuple(" " + value + " " for value in row_labels)
        if labels != expected_labels:
            raise ReportContractError(
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
