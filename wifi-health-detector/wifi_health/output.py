from __future__ import absolute_import

import csv
import io
import json
import re


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
FIELD_LABELS_EN.update({"ssid": "Wi-Fi Name (SSID)", "bssid": "Access Point BSSID", "rssi": "Signal (RSSI)", "snr": "Signal-to-Noise Ratio (SNR)", "tx_rate": "Transmit Link Rate", "rx_rate": "Receive Link Rate"})

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
REASON_ZH = {"not provided by operating system": "操作系统未提供", "not found": "未找到", "permission denied": "权限不足", "unsupported": "当前系统不支持", "default gateway not available": "默认网关不可用", "disabled by --no-public-test": "已通过 --no-public-test 禁用", "enable with --speedtest": "使用 --speedtest 开启", "download test failed": "下载测速失败"}


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


def render_csv(report, mask=False):
    stream = io.StringIO(); names = ["section", "field", "value", "unit", "availability", "source", "reason"]
    writer = csv.DictWriter(stream, fieldnames=names); writer.writeheader(); writer.writerows(flatten_report(report, mask))
    return stream.getvalue()


def _escape(value):
    if isinstance(value, (list, tuple)): value = ", ".join(str(part) for part in value)
    return str(value).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _reason(reason, language):
    return REASON_ZH.get(reason, reason or "原因未知") if language == "zh" else (reason or "reason unknown")


def _display_field(report, section, name, language, mask=False, include_unit=True):
    item = report.get(section, name)
    if not item.available:
        return "—（系统未提供：%s）" % _reason(item.reason, language) if language == "zh" else "— (Unavailable: %s)" % _reason(item.reason, language)
    value = _masked(name, item.value) if mask and name in SENSITIVE_FIELDS else item.value
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


def _localized_warning(warning, language):
    if language != "zh": return warning
    match = re.match(r"Unable to identify the Wi-Fi interface; using (\S+) fallback\.", warning)
    if match: return "无法自动识别 Wi-Fi 接口，已使用 %s 作为备用接口。" % match.group(1)
    if warning.startswith("Wireless details unavailable:"): return warning.replace("Wireless details unavailable:", "无线详情不可用：", 1)
    return warning


def _core_rows(report, language, mask):
    labels = (("Wi-Fi 名称", "无线接口", "频段 / 信道 / 频宽", "信号强度", "信噪比", "发送 / 接收速率", "网关延迟", "网关抖动 / 丢包", "公网延迟 / 丢包", "安全类型") if language == "zh" else ("Wi-Fi Name", "Wireless Interface", "Band / Channel / Width", "Signal Strength", "Signal-to-Noise Ratio", "Transmit / Receive Rate", "Gateway Latency", "Gateway Jitter / Loss", "Public Latency / Loss", "Security"))
    values = [
        _display_field(report, "connection", "ssid", language, mask), _display_field(report, "adapter", "interface", language, mask),
        " / ".join((_display_field(report, "connection", "band", language, mask), _display_field(report, "connection", "channel", language, mask), _display_field(report, "connection", "channel_width", language, mask))),
        _display_field(report, "radio", "rssi", language, mask), _display_field(report, "radio", "snr", language, mask),
        " / ".join((_display_field(report, "link", "tx_rate", language, mask), _display_field(report, "link", "rx_rate", language, mask))),
        _display_field(report, "local_quality", "latency", language, mask),
        " / ".join((_display_field(report, "local_quality", "jitter", language, mask), _display_field(report, "local_quality", "packet_loss", language, mask))),
        " / ".join((_display_field(report, "public_quality", "latency", language, mask), _display_field(report, "public_quality", "packet_loss", language, mask))),
        " / ".join((_display_field(report, "connection", "security", language, mask), _display_field(report, "connection", "authentication", language, mask), _display_field(report, "connection", "cipher", language, mask))),
    ]
    return list(zip(labels, values))


def _render_dashboard(report, language, mask):
    zh = language == "zh"; diagnosis = report.diagnosis or {}
    title = "# 📶 Wi-Fi 健康报告" if zh else "# 📶 Wi-Fi Health Report"
    metadata = "%s: %s　|　%s: %s　|　%s: %s" % (("检测时间" if zh else "Checked"), _display_field(report, "system", "checked_at", language, mask), ("系统" if zh else "System"), _display_field(report, "system", "os", language, mask), ("接口" if zh else "Interface"), _display_field(report, "adapter", "interface", language, mask))
    verdict = diagnosis.get("verdict", "insufficient_data"); badge = BADGES[language].get(verdict, BADGES[language]["insufficient_data"])
    status_headers = ("健康状态", "健康评分", "数据置信度") if zh else ("Health", "Score", "Data Confidence")
    core_headers = ("核心参数", "当前值") if zh else ("Metric", "Current Value")
    lines = [title, "", "> " + metadata, "", "| %s | %s | %s |" % status_headers, "| :---: | :---: | :---: |", "| %s | **%s/100** | **%s%%** |" % (badge, diagnosis.get("score", "—"), diagnosis.get("confidence_percent", 0)), "", "## ⭐ " + ("核心参数" if zh else "Core Metrics"), "", "| %s | %s |" % core_headers, "| --- | --- |"]
    lines.extend("| %s | %s |" % row for row in _core_rows(report, language, mask))
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
    if report.warnings: lines.extend(["", ("运行提示：" if zh else "Runtime notes:") + " " + "; ".join(_escape(_localized_warning(item, language)) for item in report.warnings)])
    return lines


def _render_details(report, language, mask):
    zh = language == "zh"; labels = SECTION_LABELS[language]; field_labels = FIELD_LABELS_ZH if zh else FIELD_LABELS_EN
    lines = ["", "## 📋 " + ("完整参数详情" if zh else "Complete Parameter Details")]
    headers = ("参数", "当前值", "单位", "状态", "来源") if zh else ("Parameter", "Value", "Unit", "Status", "Source")
    for section, fields in report.sections.items():
        lines.extend(["", "### " + labels[section], "", "| %s | %s | %s | %s | %s |" % headers, "| --- | --- | --- | :---: | --- |"])
        for name, item in fields.items():
            shown = _display_field(report, section, name, language, mask, include_unit=False)
            status = ("可用" if item.available else "不可用") if zh else ("Available" if item.available else "Unavailable")
            lines.append("| %s | %s | %s | %s | %s |" % (field_labels.get(name, name), shown, _escape(item.unit), status, _escape(item.source)))
    return lines


def render_text(report, language="zh", mask=False, view="full"):
    language = language if language in SECTION_LABELS else "zh"; view = view if view in ("full", "summary") else "full"
    lines = _render_dashboard(report, language, mask)
    if view == "full": lines.extend(_render_details(report, language, mask))
    return "\n".join(lines) + "\n"
