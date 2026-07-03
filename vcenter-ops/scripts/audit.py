"""
操作审计日志模块。
所有 vCenter 操作（含用户拒绝的）记录到 JSONL 文件。
"""

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

SKILL_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = SKILL_DIR / "logs"
AUDIT_FILE = AUDIT_DIR / "audit.log"

logger = logging.getLogger(__name__)


def _ensure_dir():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def record(
    action: str,                    # 操作类型: clone_vm, power_vm, delete_vm, snapshot, reconfigure 等
    target: str,                    # 目标 VM 名称
    status: str,                    # success / failed / rejected / dry_run
    operator: str = "agent",        # 操作者
    details: Optional[Dict] = None, # 额外详情（参数、前后状态等）
    error: Optional[str] = None,    # 错误信息
):
    """记录一条审计日志到 JSONL 文件。"""
    _ensure_dir()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": target,
        "status": status,
        "operator": operator,
        "details": details or {},
    }
    if error:
        entry["error"] = error

    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"Audit: [{status}] {action} -> {target}")


def query(action: Optional[str] = None, target: Optional[str] = None, limit: int = 50) -> list:
    """查询审计日志。"""
    if not AUDIT_FILE.exists():
        return []
    results = []
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if action and entry.get("action") != action:
                    continue
                if target and entry.get("target") != target:
                    continue
                results.append(entry)
            except json.JSONDecodeError:
                continue
    return results[-limit:]


# ============================================================
# v1.1 可视化报表
# ============================================================

def _iter_entries(since_days: Optional[int] = None):
    if not AUDIT_FILE.exists():
        return
    cutoff = None
    if since_days:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if cutoff:
                    try:
                        ts = datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
                        if ts < cutoff:
                            continue
                    except Exception:
                        pass
                yield e
            except json.JSONDecodeError:
                continue


def summarize(since_days: int = 7) -> Dict[str, Any]:
    """生成最近 N 天审计汇总。"""
    total = 0
    by_action: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_operator: Dict[str, int] = {}
    by_day: Dict[str, int] = {}
    failed_samples = []

    for e in _iter_entries(since_days=since_days):
        total += 1
        by_action[e.get("action", "?")] = by_action.get(e.get("action", "?"), 0) + 1
        by_status[e.get("status", "?")] = by_status.get(e.get("status", "?"), 0) + 1
        by_operator[e.get("operator", "?")] = by_operator.get(e.get("operator", "?"), 0) + 1
        day = (e.get("timestamp") or "")[:10]
        if day:
            by_day[day] = by_day.get(day, 0) + 1
        if e.get("status") in ("failed", "error", "rejected") and len(failed_samples) < 10:
            failed_samples.append(e)

    return {
        "period_days": since_days,
        "total": total,
        "by_action": dict(sorted(by_action.items(), key=lambda x: -x[1])),
        "by_status": by_status,
        "by_operator": by_operator,
        "by_day": dict(sorted(by_day.items())),
        "failed_samples": failed_samples,
    }


def format_report_markdown(summary: Dict[str, Any]) -> str:
    """渲染为 markdown 报表。"""
    period = summary.get("period_days", "?")
    total = summary.get("total", 0)
    lines = [
        f"# vCenter 运维审计报表 （最近 {period} 天）",
        "",
        f"- 总操作数：**{total}**",
        f"- 生成时间：{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}",
        "",
        "## 按状态分布",
        "",
        "| 状态 | 数量 |",
        "|------|------|",
    ]
    for s, c in summary.get("by_status", {}).items():
        lines.append(f"| {s} | {c} |")

    lines += [
        "",
        "## 按操作类型分布",
        "",
        "| 操作 | 数量 |",
        "|------|------|",
    ]
    for a, c in summary.get("by_action", {}).items():
        lines.append(f"| {a} | {c} |")

    lines += [
        "",
        "## 按日期趋势",
        "",
        "| 日期 | 数量 |",
        "|------|------|",
    ]
    for d, c in summary.get("by_day", {}).items():
        lines.append(f"| {d} | {c} |")

    fails = summary.get("failed_samples") or []
    if fails:
        lines += ["", "## 失败示例（剩 10 条）", "", "| 时间 | 操作 | 目标 | 状态 | 错误 |",
                  "|------|------|------|------|------|"]
        for e in fails:
            ts = (e.get("timestamp") or "")[:19]
            lines.append(
                f"| {ts} | {e.get('action','')} | {e.get('target','')} | "
                f"{e.get('status','')} | {(e.get('error') or '')[:60]} |"
            )

    return "\n".join(lines)


def format_report_html(summary: Dict[str, Any]) -> str:
    """渲染为 HTML 报表（内联 CSS，可直接在浏览器/钉钉中打开）。"""
    period = summary.get("period_days", "?")
    total = summary.get("total", 0)
    generated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    def _table(headers: list, rows: list) -> str:
        th = "".join(f"<th>{h}</th>" for h in headers)
        trs = []
        for row in rows:
            td = "".join(f"<td>{v}</td>" for v in row)
            trs.append(f"<tr>{td}</tr>")
        return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"

    def _pct_bar(pct: float, color: str = "#4caf50") -> str:
        pct = max(0, min(100, pct))
        return (
            f'<div style="background:#e0e0e0;border-radius:4px;overflow:hidden;height:18px;width:100px;display:inline-block;vertical-align:middle">'
            f'<div style="background:{color};height:100%;width:{pct}%"></div></div>'
            f' <span style="font-size:12px">{pct:.1f}%</span>'
        )

    # 状态分布
    by_status = summary.get("by_status", {})
    status_rows = []
    status_colors = {"success": "#4caf50", "warning": "#ff9800", "failed": "#f44336",
                     "error": "#f44336", "rejected": "#9e9e9e", "dry_run": "#2196f3"}
    for s, c in by_status.items():
        pct = (c / total * 100) if total else 0
        bar = _pct_bar(pct, status_colors.get(s, "#9e9e9e"))
        status_rows.append([s, c, bar])

    # 操作类型分布
    by_action = summary.get("by_action", {})
    action_rows = []
    for a, c in by_action.items():
        pct = (c / total * 100) if total else 0
        bar = _pct_bar(pct, "#2196f3")
        action_rows.append([a, c, bar])

    # 日期趋势
    by_day = summary.get("by_day", {})
    day_rows = []
    max_day = max(by_day.values()) if by_day else 1
    for d, c in by_day.items():
        pct = (c / max_day * 100) if max_day else 0
        bar = _pct_bar(pct, "#ff9800")
        day_rows.append([d, c, bar])

    # 失败示例
    fails = summary.get("failed_samples") or []
    fail_rows = []
    for e in fails:
        ts = (e.get("timestamp") or "")[:19]
        fail_rows.append([ts, e.get("action", ""), e.get("target", ""),
                          e.get("status", ""), (e.get("error") or "")[:80]])

    fail_section = ""
    if fail_rows:
        fail_section = f"""
        <div class="section">
            <h2>⚠️ 失败示例（近 10 条）</h2>
            {_table(['时间','操作','目标','状态','错误'], fail_rows)}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>vCenter 运维审计报表</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
         background: #f5f5f5; color: #333; margin: 0; padding: 20px; }}
  .container {{ max-width: 900px; margin: 0 auto; background: #fff;
                border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,.1); padding: 30px; }}
  h1 {{ color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px; }}
  h2 {{ color: #333; margin-top: 30px; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
  .kpi {{ display: flex; gap: 20px; margin: 20px 0; }}
  .kpi-card {{ flex: 1; background: #e8f0fe; border-radius: 8px; padding: 15px; text-align: center; }}
  .kpi-card .num {{ font-size: 32px; font-weight: bold; color: #1a73e8; }}
  .kpi-card .label {{ font-size: 13px; color: #666; margin-top: 4px; }}
  .section {{ margin-top: 25px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px; }}
  th {{ background: #f0f4ff; color: #333; padding: 10px; text-align: left; font-weight: 600; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #fafafa; }}
  .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #eee;
             color: #999; font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<div class="container">
  <h1>📡 vCenter 运维审计报表</h1>
  <div class="meta">统计周期：最近 <strong>{period}</strong> 天 &nbsp;|&nbsp; 生成时间：{generated}</div>

  <div class="kpi">
    <div class="kpi-card"><div class="num">{total}</div><div class="label">总操作数</div></div>
    <div class="kpi-card"><div class="num" style="color:#4caf50">{by_status.get('success',0)}</div><div class="label">成功</div></div>
    <div class="kpi-card"><div class="num" style="color:#f44336">{by_status.get('failed',0)+by_status.get('error',0)}</div><div class="label">失败</div></div>
    <div class="kpi-card"><div class="num" style="color:#2196f3">{len(by_action)}</div><div class="label">操作类型</div></div>
  </div>

  <div class="section">
    <h2>📊 按状态分布</h2>
    {_table(['状态','数量','占比'], status_rows)}
  </div>

  <div class="section">
    <h2>🔧 按操作类型分布</h2>
    {_table(['操作','数量','占比'], action_rows)}
  </div>

  <div class="section">
    <h2>📅 按日期趋势</h2>
    {_table(['日期','数量','趋势'], day_rows)}
  </div>

  {fail_section}

  <div class="footer">vCenter Ops Audit Report · Powered by 运枢</div>
</div>
</body>
</html>"""
    return html


def export_report(
    since_days: int = 7,
    fmt: str = "html",
    output: Optional[str] = None,
) -> str:
    """导出报表。fmt: html / markdown / json。"""
    s = summarize(since_days=since_days)
    if fmt == "json":
        text = json.dumps(s, ensure_ascii=False, indent=2)
    elif fmt == "markdown":
        text = format_report_markdown(s)
    else:
        text = format_report_html(s)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        logger.info(f"📊 报表已导出: {output}")
    return text


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="审计报表生成")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--fmt", choices=["html", "markdown", "json"], default="html")
    parser.add_argument("--output", help="输出文件路径")
    args = parser.parse_args()
    text = export_report(since_days=args.days, fmt=args.fmt, output=args.output)
    print(text)
