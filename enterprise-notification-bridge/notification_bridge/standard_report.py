from __future__ import absolute_import

import re


FIELD_LABELS_ZH = {
    "target": "测试目标", "reachable": "可达状态", "latency": "平均延迟",
    "jitter": "网络抖动", "packet_loss": "丢包率",
    "dns_latency": "DNS 解析延迟", "download_speed": "下载速度",
}
FIELD_LABELS_EN = {
    "target": "Target", "reachable": "Reachable", "latency": "Latency",
    "jitter": "Jitter", "packet_loss": "Packet Loss",
    "dns_latency": "DNS Latency", "download_speed": "Download Speed",
}
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
ZH_RECOMMENDATIONS = {
    "weak_signal": "靠近接入点、减少遮挡，或增加更近的 Mesh/AP 节点。",
    "moderate_signal": "优化 AP 位置或减少遮挡，以改善视频会议和游戏体验。",
    "channel_congestion": "启用自动信道选择，或选择较空闲的不重叠信道。",
    "prefer_higher_band": "覆盖足够时优先使用 5 GHz 或 6 GHz；2.4 GHz 留给远距离和旧设备。",
    "gateway_loss": "先靠近路由器复测，再检查干扰、AP 负载、固件和 Mesh 回程。",
    "upstream_loss": "优先检查运营商或上游链路，不要先修改 Wi-Fi 设置。",
    "slow_dns": "重复测试 DNS，并比较路由器/运营商 DNS 与可信公共 DNS。",
    "weak_security": "启用 WPA2-AES 或 WPA3，并设置高强度密码。",
    "no_action": "当前无需调整 Wi-Fi。",
}
ZH_ISSUES = {
    "weak_signal": "Wi-Fi 信号较弱", "moderate_signal": "Wi-Fi 信号需要关注",
    "channel_congestion": "当前信道较拥挤", "gateway_loss": "本地网关存在丢包",
    "upstream_loss": "公网链路存在丢包", "slow_dns": "DNS 解析较慢",
    "weak_security": "无线安全配置较弱",
}
EN_ISSUES = {
    "weak_signal": "Weak Wi-Fi signal", "moderate_signal": "Wi-Fi signal needs attention",
    "channel_congestion": "Channel congestion", "gateway_loss": "Packet loss to the gateway",
    "upstream_loss": "Packet loss on the public path", "slow_dns": "Slow DNS resolution",
    "weak_security": "Weak wireless security",
}
BADGES = {
    "zh": {"healthy": "✅ 健康", "warning": "⚠️ 一般/需关注", "poor": "❌ 较差", "insufficient_data": "❔ 数据不足"},
    "en": {"healthy": "✅ Healthy", "warning": "⚠️ Warning", "poor": "❌ Poor", "insufficient_data": "❔ Insufficient data"},
}
REASON_ZH = {
    "not provided by operating system": "操作系统未提供", "not found": "未找到",
    "permission denied": "权限不足", "unsupported": "当前系统不支持",
    "default gateway not available": "默认网关不可用",
    "disabled by --no-public-test": "已通过 --no-public-test 禁用",
    "enable with --speedtest": "使用 --speedtest 开启",
    "download test failed": "下载测速失败",
    "macOS does not expose the current receive PHY rate": "macOS 未提供当前接收 PHY 速率",
}


def normalize_markdown(markdown):
    return markdown.replace("\r\n", "\n")


def detect_language(markdown):
    normalized = normalize_markdown(markdown)
    if normalized.startswith("# 📶 Wi-Fi 健康报告\n"):
        return "zh"
    if normalized.startswith("# 📶 Wi-Fi Health Report\n"):
        return "en"
    return None


def _escape(value):
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(part) for part in value)
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _reason(reason, language):
    if language == "zh":
        return REASON_ZH.get(reason, reason or "原因未知")
    return reason or "reason unknown"


def _field(report_json, section, name):
    return report_json["sections"][section][name]


def _display_field(report_json, section, name, language):
    item = _field(report_json, section, name)
    if item["availability"] != "available":
        if language == "zh":
            return "—（系统未提供：%s）" % _reason(item["reason"], language)
        return "— (Unavailable: %s)" % _reason(item["reason"], language)
    value = item["value"]
    if isinstance(value, bool):
        value = ("是" if value else "否") if language == "zh" else ("Yes" if value else "No")
    shown = _escape(value)
    return shown + (" " + item["unit"] if item["unit"] else "")


def _localized_evidence(item, language):
    if language != "zh":
        return item["reason"]
    reason = item["reason"]
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
    template = templates.get(item["id"])
    return (template % value) if template and "%s" in template else (template or reason)


def _core_rows(report_json, language):
    labels = ZH_CORE_ROW_LABELS if language == "zh" else EN_CORE_ROW_LABELS
    values = [
        "%s %s" % (_display_field(report_json, "system", "os", language), _display_field(report_json, "system", "os_version", language)),
        _display_field(report_json, "system", "architecture", language),
        _display_field(report_json, "adapter", "mac", language),
        _display_field(report_json, "connection", "ssid", language),
        _display_field(report_json, "adapter", "interface", language),
        _display_field(report_json, "connection", "band", language),
        _display_field(report_json, "connection", "channel", language),
        _display_field(report_json, "connection", "channel_width", language),
        _display_field(report_json, "radio", "rssi", language),
        _display_field(report_json, "radio", "snr", language),
        _display_field(report_json, "link", "tx_rate", language),
        _display_field(report_json, "link", "rx_rate", language),
        _display_field(report_json, "local_quality", "latency", language),
        _display_field(report_json, "local_quality", "jitter", language),
        _display_field(report_json, "local_quality", "packet_loss", language),
        _display_field(report_json, "public_quality", "latency", language),
        _display_field(report_json, "public_quality", "packet_loss", language),
        _display_field(report_json, "connection", "security", language),
    ]
    return list(zip(labels, values))


def render_standard_markdown(report_json, language):
    zh = language == "zh"
    diagnosis = report_json["diagnosis"]
    title = "# 📶 Wi-Fi 健康报告" if zh else "# 📶 Wi-Fi Health Report"
    metadata = "%s: %s　|　%s: %s　|　%s: %s" % (
        "检测时间" if zh else "Checked", _display_field(report_json, "system", "checked_at", language),
        "系统" if zh else "System", _display_field(report_json, "system", "os", language),
        "接口" if zh else "Interface", _display_field(report_json, "adapter", "interface", language),
    )
    badge = BADGES[language][diagnosis["verdict"]]
    status_headers = ("健康状态", "健康评分", "数据置信度") if zh else ("Health", "Score", "Data Confidence")
    core_headers = ("核心参数", "当前值") if zh else ("Metric", "Current Value")
    lines = [
        title, "", "> " + metadata, "", "| %s | %s | %s |" % status_headers,
        "| :---: | :---: | :---: |",
        "| %s | **%s/100** | **%s%%** |" % (badge, diagnosis["score"], diagnosis["confidence_percent"]),
        "", "## ⭐ " + ("核心参数" if zh else "Core Metrics"), "",
        "| %s | %s |" % core_headers, "| --- | --- |",
    ]
    lines.extend("| %s | %s |" % row for row in _core_rows(report_json, language))
    field_labels = FIELD_LABELS_ZH if zh else FIELD_LABELS_EN
    quality_sections = (
        ("local_quality", "## 🏠 " + ("本地网络质量" if zh else "Local Network Quality"), ("target", "reachable", "latency", "jitter", "packet_loss")),
        ("public_quality", "## 🌐 " + ("公网质量" if zh else "Public Network Quality"), ("target", "reachable", "dns_latency", "latency", "jitter", "packet_loss", "download_speed")),
    )
    quality_headers = ("参数", "当前值", "状态") if zh else ("Parameter", "Current Value", "Status")
    for section, heading, names in quality_sections:
        lines.extend(["", heading, "", "| %s | %s | %s |" % quality_headers, "| --- | --- | :---: |"])
        for name in names:
            status = (("可用" if zh else "Available") if _field(report_json, section, name)["availability"] == "available" else ("不可用" if zh else "Unavailable"))
            lines.append("| %s | %s | %s |" % (field_labels[name], _display_field(report_json, section, name, language), status))
    lines.extend(["", "## 🧭 " + ("诊断与建议" if zh else "Diagnostics & Recommendations"), "", "### " + ("主要问题" if zh else "Main Issues"), ""])
    issue_labels = ZH_ISSUES if zh else EN_ISSUES
    issues = diagnosis["issues"]
    lines.extend(("- %s" % issue_labels[item] for item in issues) if issues else ["- 未发现明确问题" if zh else "- No specific issue was identified"])
    lines.extend(["", "### " + ("优化建议" if zh else "Recommendations"), ""])
    recommendations = diagnosis["recommendations"]
    if not recommendations:
        lines.append("- 暂无建议" if zh else "- No recommendation")
    for index, item in enumerate(recommendations, 1):
        priority = ({"high": "高", "medium": "中", "low": "低"}[item["priority"]] if zh else item["priority"].title())
        action = ZH_RECOMMENDATIONS[item["id"]] if zh else item["action"]
        lines.append("%d. **[%s]** %s — %s" % (index, priority, _escape(_localized_evidence(item, language)), _escape(action)))
    return "\n".join(lines) + "\n"
