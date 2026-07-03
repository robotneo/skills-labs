"""
Module: scripts.webhook_subscriber
Description: Webhook 事件订阅器。将 event_bus 事件转发到外部 HTTP 端点 / 钉钉机器人。
Author: 运枢
Date: 2026-05-22
Version: 1.1.0

设计要点：
- 订阅 event_bus，自动转发匹配事件到配置的 Webhook URL
- 支持 HTTP POST / 钉钉机器人（签名 + JSON 卡片）两种模式
- 配置持久化（data/webhooks.json），运行时可动态增删
- 失败自动重试 1 次 + 指数退避
- 投递线程异步，不阻塞主流程
"""

import os
import json
import time
import hmac
import base64
import hashlib
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from urllib.request import Request, urlopen
from urllib.error import URLError

try:
    from .event_bus import EventBus, Event, Topics, get_bus
except ImportError:
    from event_bus import EventBus, Event, Topics, get_bus

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
WEBHOOK_FILE = SKILL_DIR / "data" / "webhooks.json"
WEBHOOK_FILE.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# 配置持久化
# ============================================================

def _load_config() -> Dict[str, Any]:
    if not WEBHOOK_FILE.exists():
        return {"webhooks": []}
    try:
        return json.loads(WEBHOOK_FILE.read_text())
    except Exception:
        return {"webhooks": []}


def _save_config(data: Dict[str, Any]) -> None:
    WEBHOOK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def list_webhooks() -> List[Dict[str, Any]]:
    return _load_config().get("webhooks", [])


def add_webhook(
    name: str,
    url: str,
    secret: str = "",
    topics: Optional[List[str]] = None,
    mode: str = "http",
    enabled: bool = True,
) -> Dict[str, Any]:
    """
    注册一个 Webhook。

    :param name: Webhook 名称
    :param url: 目标 URL
    :param secret: 钉钉签名密钥（mode=dingtalk 时必填）
    :param topics: 订阅主题列表（如 ["vm.*", "clone.*"]），None=["*"]
    :param mode: http（通用 POST）/ dingtalk（钉钉机器人卡片）
    :param enabled: 是否启用
    """
    data = _load_config()
    wh = {
        "id": f"wh-{int(time.time())}-{name[:8]}",
        "name": name,
        "url": url,
        "secret": secret,
        "topics": topics or ["*"],
        "mode": mode,
        "enabled": enabled,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "last_success_at": None,
        "last_error": None,
        "deliveries": 0,
    }
    data["webhooks"].append(wh)
    _save_config(data)
    logger.info(f"✅ Webhook [{name}] 已注册: {url}")
    return wh


def remove_webhook(wh_id: str) -> bool:
    data = _load_config()
    before = len(data["webhooks"])
    data["webhooks"] = [w for w in data["webhooks"] if w["id"] != wh_id]
    if len(data["webhooks"]) < before:
        _save_config(data)
        return True
    return False


def toggle_webhook(wh_id: str, enabled: bool) -> bool:
    data = _load_config()
    for w in data["webhooks"]:
        if w["id"] == wh_id:
            w["enabled"] = enabled
            _save_config(data)
            return True
    return False


# ============================================================
# 投递引擎
# ============================================================

def _sign_dingtalk(secret: str, ts: int) -> str:
    """钉钉机器人签名。"""
    string_to_sign = f"{ts}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _deliver_http(url: str, payload: Dict[str, Any], secret: str = "") -> bool:
    """通用 HTTP POST 投递。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning(f"HTTP 投递失败 [{url}]: {e}")
        return False


def _deliver_dingtalk(url: str, secret: str, event: Event) -> bool:
    """钉钉机器人投递（markdown 卡片）。"""
    ts = int(time.time() * 1000)
    signed_url = url
    if secret:
        sign = _sign_dingtalk(secret, ts)
        signed_url = f"{url}&timestamp={ts}&sign={sign}"

    topic = event.get("topic", "?")
    p = event.get("payload", {})
    ts_str = event.get("ts", "?")

    # 构建 markdown 消息
    md_lines = [f"### 📡 {topic}", f"> 时间: {ts_str}", ""]
    for k, v in p.items():
        md_lines.append(f"- **{k}**: {v}")

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"vCenter 事件: {topic}",
            "text": "\n".join(md_lines),
        },
    }
    return _deliver_http(signed_url, payload)


def _do_deliver(wh: Dict[str, Any], event: Event) -> None:
    """单次投递（含重试）。"""
    url = wh["url"]
    mode = wh.get("mode", "http")

    for attempt in range(2):
        if mode == "dingtalk":
            ok = _deliver_dingtalk(url, wh.get("secret", ""), event)
        else:
            ok = _deliver_http(url, {
                "webhook": wh["name"],
                "event": event,
            })
        if ok:
            # 更新统计
            data = _load_config()
            for w in data["webhooks"]:
                if w["id"] == wh["id"]:
                    w["last_success_at"] = datetime.now().isoformat(timespec="seconds")
                    w["deliveries"] = w.get("deliveries", 0) + 1
                    w["last_error"] = None
                    break
            _save_config(data)
            return

        # 重试
        if attempt == 0:
            time.sleep(1)
            continue

        # 最终失败
        data = _load_config()
        for w in data["webhooks"]:
            if w["id"] == wh["id"]:
                w["last_error"] = f"投递失败 ({event['topic']})"
                break
        _save_config(data)


def _on_event(wh: Dict[str, Any], event: Event) -> None:
    """event_bus 回调：过滤 topic + 异步投递。"""
    topics = wh.get("topics") or ["*"]
    event_topic = event.get("topic", "")
    matched = any(
        EventBus._match(t, event_topic) for t in topics
    )
    if not matched:
        return
    # 异步投递（不阻塞事件发布者）
    threading.Thread(
        target=_do_deliver,
        args=(wh, event),
        daemon=True,
        name=f"webhook-{wh['name']}",
    ).start()


# ============================================================
# 自动注册：读取 data/webhooks.json 并挂到 event_bus
# ============================================================

_registered = False


def register_all_to_bus() -> int:
    """
    读取所有已配置 Webhook，注册到 event_bus。
    返回注册数量。幂等：多次调用只注册一次。
    """
    global _registered
    if _registered:
        return 0
    _registered = True

    bus = get_bus()
    webhooks = list_webhooks()
    count = 0
    for wh in webhooks:
        if not wh.get("enabled", True):
            continue
        # 为每个 webhook 创建独立闭包
        handler = lambda event, _wh=wh: _on_event(_wh, event)
        for pattern in (wh.get("topics") or ["*"]):
            bus.subscribe(pattern, handler)
        count += 1
        logger.info(f"📡 Webhook [{wh['name']}] 已挂载: {wh.get('topics')}")
    return count


def format_webhook_list(webhooks: List[Dict[str, Any]]) -> str:
    if not webhooks:
        return "📭 暂无 Webhook 订阅"
    lines = ["| ID | 名称 | 模式 | 主题 | 启用 | 投递次数 |", "|----|------|------|------|------|---------|"]
    for w in webhooks:
        lines.append(
            f"| {w['id'][:16]} | {w['name']} | {w.get('mode','http')} | "
            f"{','.join(w.get('topics',[]))} | {'✅' if w.get('enabled') else '❌'} | "
            f"{w.get('deliveries',0)} |"
        )
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="Webhook 订阅管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出所有 Webhook")

    p_add = sub.add_parser("add", help="添加 Webhook")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--url", required=True)
    p_add.add_argument("--secret", default="")
    p_add.add_argument("--topics", nargs="+", default=["*"])
    p_add.add_argument("--mode", choices=["http", "dingtalk"], default="http")

    p_rm = sub.add_parser("remove", help="删除 Webhook")
    p_rm.add_argument("wh_id")

    args = parser.parse_args()

    if args.cmd == "list":
        print(format_webhook_list(list_webhooks()))
    elif args.cmd == "add":
        wh = add_webhook(args.name, args.url, secret=args.secret, topics=args.topics, mode=args.mode)
        print(f"✅ 已添加: {json.dumps(wh, ensure_ascii=False, indent=2)}")
    elif args.cmd == "remove":
        ok = remove_webhook(args.wh_id)
        print(f"{'✅ 已删除' if ok else '⚠️ 未找到'}: {args.wh_id}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
