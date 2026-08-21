from __future__ import absolute_import

import csv
import io
import json
import re


SECTION_LABELS = {
    "zh": {
        "system": "系统", "adapter": "无线适配器", "connection": "Wi-Fi 连接",
        "radio": "射频", "link": "链路", "ip": "IP 网络",
        "local_quality": "本地网络质量", "public_quality": "公网质量", "diagnosis": "诊断",
    },
    "en": {
        "system": "System", "adapter": "Wireless Adapter", "connection": "Wi-Fi Connection",
        "radio": "Radio", "link": "Link", "ip": "IP Network",
        "local_quality": "Local Network Quality", "public_quality": "Public Network Quality", "diagnosis": "Diagnostics",
    },
}

SENSITIVE_FIELDS = {"ssid", "bssid", "mac", "ipv4", "ipv6", "gateway", "dns_servers"}

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

ZH_VERDICTS = {"healthy": "健康", "warning": "一般/需关注", "poor": "较差", "insufficient_data": "数据不足，无法完整判断"}


def _masked(name, value):
    if value is None:
        return value
    text = str(value)
    if name == "ssid":
        return "***"
    if name in ("mac", "bssid"):
        parts = re.split("[:-]", text)
        if len(parts) == 6:
            return ":".join(parts[:2] + ["**", "**"] + parts[-2:])
        return "***"
    if name in ("ipv4", "gateway"):
        parts = text.split(".")
        if len(parts) == 4:
            return ".".join(parts[:2] + ["***", parts[-1]])
    if name == "ipv6":
        return text.split(":", 2)[0] + ":***"
    if name == "dns_servers":
        return "***"
    return text


def flatten_report(report, mask=False):
    rows = []
    for section, fields in report.sections.items():
        for name, item in fields.items():
            value = item.value
            if mask and name in SENSITIVE_FIELDS:
                value = _masked(name, value)
            rows.append({
                "section": section,
                "field": name,
                "value": "" if value is None else value,
                "unit": item.unit,
                "availability": item.availability,
                "source": item.source,
                "reason": item.reason,
            })
    return rows


def _masked_dict(report, mask):
    payload = report.to_dict()
    if mask:
        for fields in payload["sections"].values():
            for name, item in fields.items():
                if name in SENSITIVE_FIELDS:
                    item["value"] = _masked(name, item["value"])
    return payload


def render_json(report, mask=False):
    return json.dumps(_masked_dict(report, mask), ensure_ascii=False, indent=2)


def render_csv(report, mask=False):
    stream = io.StringIO()
    names = ["section", "field", "value", "unit", "availability", "source", "reason"]
    writer = csv.DictWriter(stream, fieldnames=names)
    writer.writeheader()
    writer.writerows(flatten_report(report, mask))
    return stream.getvalue()


def render_text(report, language="zh", mask=False):
    language = language if language in SECTION_LABELS else "zh"
    labels = SECTION_LABELS[language]
    unavailable_label = "不可用" if language == "zh" else "Unavailable"
    lines = []
    for section, fields in report.sections.items():
        header = "| 参数 | 当前值 | 单位 | 来源 |" if language == "zh" else "| Parameter | Value | Unit | Source |"
        lines.extend(["", "## " + labels[section], "", header, "| --- | --- | --- | --- |"])
        for name, item in fields.items():
            if item.available:
                value = _masked(name, item.value) if mask and name in SENSITIVE_FIELDS else item.value
                shown = str(value)
            else:
                shown = unavailable_label + (": " + item.reason if item.reason else "")
            lines.append("| %s | %s | %s | %s |" % (name, shown, item.unit, item.source))
    diagnosis = report.diagnosis or {}
    lines.extend(["", "## " + labels["diagnosis"], ""])
    verdict = diagnosis.get("verdict", "insufficient_data")
    if language == "zh":
        lines.append("- 结论: %s" % ZH_VERDICTS.get(verdict, verdict))
        lines.append("- 健康评分: %s/100" % diagnosis.get("score", "-"))
        lines.append("- 数据置信度: %s%%" % diagnosis.get("confidence_percent", 0))
    else:
        lines.append("- Verdict: %s" % verdict)
        lines.append("- Score: %s/100" % diagnosis.get("score", "-"))
        lines.append("- Data confidence: %s%%" % diagnosis.get("confidence_percent", 0))
    if report.warnings:
        lines.append("- Warnings: " + "; ".join(report.warnings))
    recommendations = diagnosis.get("recommendations", [])
    if recommendations:
        lines.extend(["", "优化建议:" if language == "zh" else "Recommendations:"])
        for index, item in enumerate(recommendations, 1):
            action = ZH_RECOMMENDATIONS.get(item["id"], item["action"]) if language == "zh" else item["action"]
            lines.append("%d. [%s] %s — %s" % (index, item["priority"], item["reason"], action))
    return "\n".join(lines).lstrip() + "\n"
