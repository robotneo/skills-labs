from __future__ import absolute_import


def _number(report, section, name):
    item = report.get(section, name)
    if not item.available:
        return None
    try:
        return float(item.value)
    except (TypeError, ValueError):
        return None


def _text(report, section, name):
    item = report.get(section, name)
    return str(item.value) if item.available else ""


def diagnose(report):
    score = 100
    observed = 0
    possible = 10
    issues = []
    recommendations = []
    categories = {"signal": 100, "interference": 100, "link": 100, "local": 100, "public": 100, "security": 100}

    rssi = _number(report, "radio", "rssi")
    snr = _number(report, "radio", "snr")
    if rssi is not None:
        observed += 1
        if rssi < -75:
            score -= 30; categories["signal"] -= 60
            issues.append("weak_signal")
            recommendations.append({"id": "weak_signal", "priority": "high", "reason": "RSSI %.0f dBm" % rssi, "action": "Move closer to the access point, reduce obstructions, or add a nearer mesh/AP node."})
        elif rssi < -67:
            score -= 15; categories["signal"] -= 30
            issues.append("moderate_signal")
            recommendations.append({"id": "moderate_signal", "priority": "medium", "reason": "RSSI %.0f dBm" % rssi, "action": "Improve AP placement or reduce obstructions for real-time traffic."})
    elif snr is not None:
        observed += 1
        if snr < 15:
            score -= 30; categories["signal"] -= 60
        elif snr < 25:
            score -= 15; categories["signal"] -= 30

    same = _number(report, "radio", "same_channel_networks")
    if same is not None:
        observed += 1
        if same >= 4:
            score -= 10; categories["interference"] -= 35
            issues.append("channel_congestion")
            recommendations.append({"id": "channel_congestion", "priority": "medium", "reason": "%d nearby networks share the channel" % same, "action": "Use automatic channel selection or choose a less congested non-overlapping channel."})

    band = _text(report, "connection", "band")
    if band:
        observed += 1
        if band.startswith("2.4") and same is not None and same >= 4:
            recommendations.append({"id": "prefer_higher_band", "priority": "medium", "reason": "The 2.4 GHz channel is congested", "action": "Prefer 5 GHz or 6 GHz when coverage is adequate; keep 2.4 GHz for range and legacy devices."})

    tx_rate = _number(report, "link", "tx_rate")
    if tx_rate is not None:
        observed += 1
        if tx_rate < 20:
            score -= 20; categories["link"] -= 60
        elif tx_rate < 50:
            score -= 10; categories["link"] -= 30

    local_loss = _number(report, "local_quality", "packet_loss")
    local_latency = _number(report, "local_quality", "latency")
    if local_loss is not None:
        observed += 1
        if local_loss > 3:
            deduction = min(30, int(local_loss * 2))
            score -= deduction; categories["local"] -= min(70, deduction * 2)
            issues.append("gateway_loss")
            recommendations.append({"id": "gateway_loss", "priority": "high", "reason": "Gateway packet loss %.1f%%" % local_loss, "action": "Test near the router; then check interference, AP load, firmware, and mesh backhaul."})
    if local_latency is not None:
        observed += 1
        if local_latency > 50:
            score -= 10; categories["local"] -= 30

    public_loss = _number(report, "public_quality", "packet_loss")
    if public_loss is not None:
        observed += 1
        if public_loss > 3 and (local_loss is None or local_loss <= 1):
            score -= 8; categories["public"] -= 30
            issues.append("upstream_loss")
            recommendations.append({"id": "upstream_loss", "priority": "medium", "reason": "Public loss is elevated while the gateway is stable", "action": "Check the ISP/upstream path rather than changing Wi-Fi settings first."})

    dns_latency = _number(report, "public_quality", "dns_latency")
    if dns_latency is not None:
        observed += 1
        if dns_latency > 250:
            score -= 5; categories["public"] -= 15
            issues.append("slow_dns")
            recommendations.append({"id": "slow_dns", "priority": "medium", "reason": "DNS lookup took %.0f ms" % dns_latency, "action": "Retest DNS and compare the router/ISP resolver with a trusted public resolver."})

    security = (_text(report, "connection", "security") + " " + _text(report, "connection", "authentication")).lower()
    if security:
        observed += 1
        if any(token in security for token in ("open", "wep", "开放")):
            score -= 20; categories["security"] -= 70
            issues.append("weak_security")
            recommendations.append({"id": "weak_security", "priority": "high", "reason": "Open or obsolete Wi-Fi security was detected", "action": "Enable WPA2-AES or WPA3 and use a strong passphrase."})

    score = max(0, min(100, score))
    confidence = int(round(observed * 100.0 / possible))
    if confidence < 25:
        verdict = "insufficient_data"
    elif score >= 85:
        verdict = "healthy"
    elif score >= 65:
        verdict = "warning"
    else:
        verdict = "poor"
    if not recommendations and confidence >= 25:
        recommendations.append({"id": "no_action", "priority": "low", "reason": "No material issue was observed", "action": "No Wi-Fi change is currently recommended."})
    return {
        "score": score,
        "confidence_percent": confidence,
        "verdict": verdict,
        "category_scores": categories,
        "issues": issues,
        "recommendations": recommendations,
    }
