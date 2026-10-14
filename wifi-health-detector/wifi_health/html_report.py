"""Self-contained, fixed-layout HTML renderer for the Wi-Fi health report.

The DingTalk clients (desktop / mobile / web) render Markdown bubbles
differently, so cross-version consistency cannot be achieved inside a chat
message. Instead the canonical report is also rendered as a single, fully
inline-styled HTML document that every client opens in its system webview /
browser, where the layout is deterministic.

Design constraints (do not relax without updating the tests):
  * standard library only -- no third-party template/CSS dependency;
  * one string in, one string out: ``render_html(report_json, language)``;
  * every dynamic value is HTML-escaped (SSID/BSSID are untrusted text);
  * all styles are inline in a single <style> block: no external assets,
    fonts, scripts or network references, so it renders identically offline;
  * the input is the same schema-2.0 report JSON that travels inside the
    delivery envelope (already masked when the caller asked for masking).
"""
from __future__ import absolute_import

import html
from datetime import datetime

from . import __version__ as DETECTOR_VERSION
from .output import (
    BADGES,
    EN_ISSUES,
    FIELD_LABELS_EN,
    FIELD_LABELS_ZH,
    REASON_ZH,
    SECTION_LABELS,
    ZH_ISSUES,
    ZH_RECOMMENDATIONS,
    _localized_evidence,
)


# Detailed sections shown after the quality panels, in presentation order.
_DETAIL_SECTIONS = (
    "system", "adapter", "connection", "radio", "link", "ip",
)
_QUALITY_FIELDS = {
    "local_quality": ("target", "reachable", "latency", "jitter", "packet_loss"),
    "public_quality": (
        "target", "reachable", "dns_latency", "latency", "jitter",
        "packet_loss", "download_speed",
    ),
}
_CORE_METRICS = (
    ("connection", "ssid"), ("connection", "band"),
    ("connection", "channel"), ("connection", "channel_width"),
    ("radio", "rssi"), ("radio", "snr"),
    ("link", "tx_rate"), ("link", "rx_rate"),
    ("local_quality", "latency"), ("local_quality", "packet_loss"),
    ("public_quality", "latency"), ("public_quality", "packet_loss"),
    ("connection", "security"), ("adapter", "mac"),
)

_VERDICT_TONE = {
    "healthy": "#34d399",
    "warning": "#fbbf24",
    "poor": "#f87171",
    "insufficient_data": "#94a3b8",
}
_PRIORITY_LABEL = {
    "zh": {"high": "高", "medium": "中", "low": "低"},
    "en": {"high": "High", "medium": "Medium", "low": "Low"},
}


class HtmlReportError(RuntimeError):
    pass


def render_html(report_json, language="zh"):
    """Return a deterministic, self-contained HTML document for ``report_json``."""
    if not isinstance(report_json, dict):
        raise HtmlReportError("report JSON must be an object")
    language = language if language in SECTION_LABELS else "zh"
    zh = language == "zh"
    sections = report_json.get("sections", {})
    diagnosis = report_json.get("diagnosis", {}) or {}
    warnings = report_json.get("warnings", []) or []

    verdict = diagnosis.get("verdict", "insufficient_data")
    score = _as_number(diagnosis.get("score"))
    confidence = _as_number(diagnosis.get("confidence_percent"))
    tone = _VERDICT_TONE.get(verdict, _VERDICT_TONE["insufficient_data"])
    badge = BADGES[language].get(verdict, BADGES[language]["insufficient_data"])

    title = "Wi-Fi 健康报告" if zh else "Wi-Fi Health Report"
    raw_checked = _display(sections, "system", "checked_at", language)
    checked = _format_timestamp(raw_checked, language)
    system = _display(sections, "system", "os", language)
    interface = _display(sections, "adapter", "interface", language)
    subtitle_parts = [
        ("%s：%s" % (("检测时间" if zh else "Checked"), checked)),
        ("%s：%s" % (("系统" if zh else "System"), system)),
        ("%s：%s" % (("接口" if zh else "Interface"), interface)),
    ]

    head = (
        '<!doctype html>\n<html lang="%s">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="dark">\n<title>%s</title>\n'
        '<style>%s</style>\n</head>\n'
    ) % (language, _esc(title), _STYLE)

    body = ['<body>', '<main class="sheet">']
    body.append(_hero(title, subtitle_parts, score, confidence, badge, tone, zh))
    body.append(_core_grid(sections, language))
    body.append(_quality_panels(sections, language))
    body.append(_diagnosis_panel(diagnosis, tone, language))
    body.append(_detail_panels(sections, language))
    if warnings:
        body.append(_warnings_panel(warnings, zh))
    body.append(_footer(checked, zh))
    body.append('</main>')
    body.append('</body>\n</html>\n')
    return head + "\n".join(body)


def write_html_file(report_json, path, language="zh"):
    """Render and persist the HTML document with private owner permissions."""
    document = render_html(report_json, language)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(document)
    return path


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def _hero(title, subtitle_parts, score, confidence, badge, tone, zh):
    score_label = "健康评分" if zh else "Score"
    conf_label = "数据置信度" if zh else "Confidence"
    ring = _score_ring(score, tone)
    subtitles = "　·　".join(subtitle_parts)
    return (
        '<section class="hero">'
        '<div class="hero-text">'
        '<div class="kicker">Wi-Fi HEALTH</div>'
        '<h1>%s</h1>'
        '<p class="subtitle">%s</p>'
        '<div class="badge" style="--tone:%s">%s</div>'
        '</div>'
        '<div class="hero-side">%s'
        '<div class="ring-meta"><span class="ring-label">%s</span>'
        '<span class="ring-conf">%s <strong>%s%%</strong></span></div>'
        '</div>'
        '</section>'
    ) % (
        _esc(title), _esc(subtitles), tone, _esc(badge),
        ring, _esc(score_label), _esc(conf_label),
        _esc("—" if confidence is None else str(int(confidence))),
    )


def _score_ring(score, tone):
    """Deterministic SVG progress ring (no conic-gradient dependency)."""
    if score is None:
        shown = "—"
        fraction = 0
    else:
        shown = str(int(score))
        fraction = max(0, min(100, score)) / 100.0
    radius = 52
    circumference = 2 * 3.141592653589793 * radius
    dash = circumference * fraction
    return (
        '<div class="ring" style="--tone:%s">'
        '<svg viewBox="0 0 120 120" width="120" height="120" role="img">'
        '<circle class="ring-track" cx="60" cy="60" r="%s" />'
        '<circle class="ring-fill" cx="60" cy="60" r="%s" '
        'transform="rotate(-90 60 60)" stroke-dasharray="%.2f %.2f" />'
        '</svg><span class="ring-num">%s</span></div>'
    ) % (tone, radius, radius, dash, circumference, _esc(shown))


def _core_grid(sections, language):
    zh = language == "zh"
    labels = FIELD_LABELS_ZH if zh else FIELD_LABELS_EN
    cards = []
    for section, name in _CORE_METRICS:
        value, tone_class = _value_with_tone(sections, section, name, language)
        cards.append(
            '<li class="metric %s"><span class="metric-label">%s</span>'
            '<span class="metric-value">%s</span></li>'
            % (tone_class, _esc(labels.get(name, name)), value)
        )
    heading = "核心参数" if zh else "Core Metrics"
    return ('<section class="block"><h2>⭐ %s</h2>'
            '<ul class="metric-grid">%s</ul></section>') % (
        _esc(heading), "".join(cards))


def _quality_panels(sections, language):
    zh = language == "zh"
    panels = []
    icons = {"local_quality": "🏠", "public_quality": "🌐"}
    for section in ("local_quality", "public_quality"):
        rows = []
        for name in _QUALITY_FIELDS[section]:
            item = _field(sections, section, name)
            available = bool(item and item.get("availability") == "available")
            dot = "up" if available else "down"
            value = _display(sections, section, name, language)
            label = (FIELD_LABELS_ZH if zh else FIELD_LABELS_EN).get(name, name)
            status = ("可用" if available else "不可用") if zh else (
                "Available" if available else "Unavailable")
            rows.append(
                '<tr><th>%s</th><td class="qv">%s</td>'
                '<td class="qs"><span class="dot %s"></span>%s</td></tr>'
                % (_esc(label), value, dot, _esc(status))
            )
        heading = SECTION_LABELS[language][section]
        panels.append(
            '<section class="block panel"><h2>%s %s</h2>'
            '<table class="quality"><tbody>%s</tbody></table></section>'
            % (icons[section], _esc(heading), "".join(rows))
        )
    return '<div class="panel-row">%s</div>' % "".join(panels)


def _diagnosis_panel(diagnosis, tone, language):
    zh = language == "zh"
    issue_labels = ZH_ISSUES if zh else EN_ISSUES
    issues = diagnosis.get("issues", []) or []
    if issues:
        chips = "".join(
            '<li class="chip">%s</li>'
            % _esc(issue_labels.get(code, code)) for code in issues
        )
    else:
        chips = ('<li class="chip good">%s</li>'
                 % _esc("未发现明确问题" if zh else "No specific issue identified"))
    issues_heading = "主要问题" if zh else "Main Issues"

    recommendations = diagnosis.get("recommendations", []) or []
    cards = []
    for index, item in enumerate(recommendations, 1):
        priority = str(item.get("priority", "low"))
        prio_text = _PRIORITY_LABEL[language].get(priority, priority)
        reason = _recommendation_reason(item, language)
        action = _recommendation_action(item, zh)
        cards.append(
            '<li class="rec"><div class="rec-top"><span class="rec-no">#%d</span>'
            '<span class="rec-prio p-%s">%s</span></div>'
            '<p class="rec-reason">%s</p><p class="rec-action">%s</p></li>'
            % (index, _esc(priority), _esc(prio_text),
               _esc(reason), _esc(action))
        )
    if not cards:
        cards.append('<li class="rec"><p class="rec-action">%s</p></li>'
                     % _esc("暂无建议" if zh else "No recommendation"))
    rec_heading = "优化建议" if zh else "Recommendations"
    return (
        '<section class="block diag" style="--tone:%s">'
        '<h2>🧭 %s</h2>'
        '<h3>%s</h3><ul class="chips">%s</ul>'
        '<h3>%s</h3><ul class="recs">%s</ul>'
        '</section>'
    ) % (
        tone, _esc("诊断与建议" if zh else "Diagnostics &amp; Recommendations"),
        _esc(issues_heading), chips, _esc(rec_heading), "".join(cards),
    )


def _detail_panels(sections, language):
    zh = language == "zh"
    labels = FIELD_LABELS_ZH if zh else FIELD_LABELS_EN
    blocks = []
    for section in _DETAIL_SECTIONS:
        rows = []
        names = sections.get(section, {})
        for name, item in names.items():
            value, _tone = _value_with_tone(sections, section, name, language)
            rows.append(
                '<div class="kv"><dt>%s</dt><dd>%s</dd></div>'
                % (_esc(labels.get(name, name)), value)
            )
        blocks.append(
            '<section class="block detail"><h2>%s</h2>'
            '<dl class="kv-grid">%s</dl></section>'
            % (_esc(SECTION_LABELS[language][section]), "".join(rows))
        )
    return "".join(blocks)


def _warnings_panel(warnings, zh):
    items = "".join(
        '<li>%s</li>' % _esc(str(item)) for item in warnings if str(item).strip()
    )
    if not items:
        return ""
    heading = "采集告警" if zh else "Collection Warnings"
    return ('<section class="block warnings"><h2>⚠️ %s</h2>'
            '<ul>%s</ul></section>') % (_esc(heading), items)


def _footer(checked, zh):
    generated = ("由 wifi-health-detector %s 生成" if zh
                 else "Generated by wifi-health-detector %s") % DETECTOR_VERSION
    return ('<footer class="foot"><span>%s</span><span>%s</span></footer>'
            % (_esc(generated), _esc(checked)))


# --------------------------------------------------------------------------- #
# Value formatting (mirrors output.py but operates on the JSON dict)
# --------------------------------------------------------------------------- #

def _field(sections, section, name):
    return sections.get(section, {}).get(name) or {}


def _display(sections, section, name, language):
    value, _tone = _value_with_tone(sections, section, name, language)
    return value


def _value_with_tone(sections, section, name, language):
    item = _field(sections, section, name)
    if item.get("availability") != "available" or item.get("value") is None:
        reason_text = _reason_text(item.get("reason", ""), language)
        muted = _esc("—") + (
            '<span class="na">%s</span>' % _esc(reason_text) if reason_text else ""
        )
        return muted, "is-na"
    raw = item.get("value")
    if isinstance(raw, bool):
        text = ("是" if raw else "否") if language == "zh" else ("Yes" if raw else "No")
    elif isinstance(raw, (list, tuple)):
        text = ", ".join(str(part) for part in raw)
    else:
        text = str(raw)
    unit = item.get("unit") or ""
    shown = _esc(text) + (' <span class="unit">%s</span>' % _esc(unit) if unit else "")
    tone = "is-good" if _is_positive(section, name, raw) else ""
    return shown, tone


def _is_positive(section, name, value):
    """Best-effort semantic tint for a few connectivity/quality fields."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if section == "radio" and name == "rssi":
        return value >= -65
    if section == "radio" and name == "snr":
        return value >= 25
    if section in ("local_quality", "public_quality"):
        if name in ("latency", "dns_latency", "jitter", "packet_loss"):
            threshold = 2.0 if name == "packet_loss" else (
                150 if name == "dns_latency" else 80)
            return value <= threshold
    return False


def _recommendation_reason(item, language):
    # Evidence line, identical source to the canonical Markdown view (e.g.
    # "RSSI 为 -71 dBm"). Falls back to the machine-provided reason. This must
    # stay distinct from the action (ZH_RECOMMENDATIONS) to avoid showing the
    # same recommendation text twice on the card.
    try:
        evidence = _localized_evidence(item, language)
    except Exception:
        evidence = ""
    if isinstance(evidence, str) and evidence.strip():
        return evidence
    return str(item.get("reason", "") or "")


def _recommendation_action(item, language):
    # The localized action catalog for Chinese; English uses the JSON action.
    if language == "zh":
        return ZH_RECOMMENDATIONS.get(item.get("id"), item.get("action", ""))
    return str(item.get("action", "") or "")


def _reason_text(reason, language):
    if not reason:
        return ""
    if language == "zh":
        return REASON_ZH.get(reason, reason)
    return reason


def _as_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _format_timestamp(value, language):
    """Render the RFC3339 checked_at value as readable local time."""
    if not isinstance(value, str) or not value:
        return value if isinstance(value, str) else ""
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return text
    template = "%Y-%m-%d %H:%M" if language == "zh" else "%Y-%m-%d %H:%M"
    return parsed.strftime(template)


def _esc(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


# Fixed design tokens. Everything is inline in this single block; no external
# font/image/script is referenced so the document renders identically offline
# in every DingTalk webview/browser.
_STYLE = """
:root{
  --bg0:#0b1020; --bg1:#131a2e; --ink:#e8edf7; --muted:#9aa6c0;
  --line:rgba(255,255,255,.08); --card:rgba(255,255,255,.045);
  --card2:rgba(255,255,255,.07); --accent:#5b8cff;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  color:var(--ink); line-height:1.55;
  background:
    radial-gradient(1100px 600px at 85% -10%, rgba(91,140,255,.22), transparent 60%),
    radial-gradient(900px 500px at -10% 0%, rgba(52,211,153,.16), transparent 55%),
    linear-gradient(160deg,#0b1020 0%,#0d1326 45%,#0a0f1d 100%);
  background-attachment:fixed;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
.sheet{max-width:920px;margin:0 auto;padding:32px 22px 56px}
.block,.hero{
  background:var(--card); border:1px solid var(--line);
  border-radius:18px; padding:20px 22px; margin:18px 0;
  box-shadow:0 18px 50px -28px rgba(0,0,0,.8), inset 0 1px 0 rgba(255,255,255,.05);
  backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px);
}
h1{font-size:27px;line-height:1.25;margin:6px 0 8px;letter-spacing:.5px}
h2{font-size:17px;margin:0 0 14px;color:#dfe7f7;font-weight:700}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.12em;
  color:var(--muted);margin:18px 0 10px}
p{margin:0}
.hero{display:flex;align-items:center;justify-content:space-between;gap:24px;
  padding:28px 30px;
  background:linear-gradient(135deg,rgba(91,140,255,.16),rgba(52,211,153,.08) 60%,rgba(255,255,255,.03));
}
.hero-text{min-width:0}
.kicker{font-size:11px;letter-spacing:.28em;color:#8fb0ff;font-weight:700}
.subtitle{color:var(--muted);font-size:13px;margin-bottom:14px}
.badge{display:inline-block;padding:6px 14px;border-radius:999px;font-weight:700;
  font-size:13px;color:var(--tone);
  background:color-mix(in srgb,var(--tone) 14%,transparent);
  border:1px solid color-mix(in srgb,var(--tone) 45%,transparent)}
.hero-side{display:flex;align-items:center;gap:16px;flex-shrink:0}
.ring{position:relative;width:120px;height:120px;display:grid;place-items:center}
.ring svg{position:absolute;inset:0}
.ring-track{fill:none;stroke:rgba(255,255,255,.10);stroke-width:10}
.ring-fill{fill:none;stroke:var(--tone);stroke-width:10;stroke-linecap:round;
  transition:stroke-dasharray .6s ease}
.ring-num{font-size:30px;font-weight:800}
.ring-meta{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted)}
.ring-meta strong{color:var(--ink);font-size:15px}
.metric-grid{list-style:none;margin:0;padding:0;
  display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.metric{background:var(--card2);border:1px solid var(--line);border-radius:12px;
  padding:11px 13px;display:flex;flex-direction:column;gap:4px;min-width:0}
.metric-label{font-size:11px;color:var(--muted)}
.metric-value{font-size:15px;font-weight:650;word-break:break-word}
.metric.is-good .metric-value{color:#5eead4}
.metric.is-na{opacity:.72}
.unit{color:var(--muted);font-weight:500;font-size:12px}
.na{display:block;color:var(--muted);font-size:11px;margin-top:2px;font-weight:400}
.panel-row{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.panel{margin:0}
table.quality{width:100%;border-collapse:collapse;font-size:13px}
.quality th,.quality td{text-align:left;padding:8px 8px;border-bottom:1px solid var(--line);
  vertical-align:middle}
.quality th{color:var(--muted);font-weight:500}
.quality td.qv{font-weight:600}
.quality td.qs{text-align:right;white-space:nowrap;color:var(--muted);font-size:12px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot.up{background:#34d399;box-shadow:0 0 8px rgba(52,211,153,.8)}
.dot.down{background:#64748b}
.diag{border-color:color-mix(in srgb,var(--tone) 35%,transparent)}
.chips{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.chip{padding:6px 12px;border-radius:999px;font-size:12.5px;
  background:rgba(248,113,113,.12);border:1px solid rgba(248,113,113,.4);color:#fecaca}
.chip.good{background:rgba(52,211,153,.12);border-color:rgba(52,211,153,.4);color:#a7f3d0}
.recs{list-style:none;margin:0;padding:0;display:grid;
  grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.rec{background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:13px 15px}
.rec-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.rec-no{font-size:12px;color:var(--muted);font-weight:700}
.rec-prio{font-size:11px;padding:2px 9px;border-radius:999px;font-weight:700}
.p-high{background:rgba(248,113,113,.18);color:#fca5a5}
.p-medium{background:rgba(251,191,36,.16);color:#fcd34d}
.p-low{background:rgba(52,211,153,.14);color:#6ee7b7}
.rec-reason{font-size:13px;font-weight:600;margin-bottom:5px}
.rec-action{font-size:12.5px;color:var(--muted)}
.kv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:0 22px;margin:0}
.kv{display:flex;justify-content:space-between;gap:14px;padding:8px 0;
  border-bottom:1px solid var(--line);min-width:0}
.kv dt{color:var(--muted);font-size:12.5px;margin:0;flex-shrink:0}
.kv dd{margin:0;text-align:right;font-size:13px;font-weight:600;word-break:break-word}
.kv .is-na dd,.kv .is-na{opacity:.75}
.warnings{border-color:rgba(251,191,36,.35)}
.warnings ul{margin:0;padding-left:18px;font-size:13px;color:#fde68a}
.foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;
  color:var(--muted);font-size:11.5px;padding:6px 6px 0}
@media (max-width:680px){
  .hero{flex-direction:column;align-items:flex-start}
  .hero-side{align-self:stretch;justify-content:space-between}
  .panel-row{grid-template-columns:1fr}
  h1{font-size:23px}
}
@media print{
  body{background:#fff;color:#111}
  .block,.hero,.panel{break-inside:avoid;box-shadow:none;
    border-color:#ddd;background:#fff;color:#111}
  .metric-value,.quality td.qv,.rec-reason,.kv dd{color:#111}
}
"""
