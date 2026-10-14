# -*- coding: utf-8 -*-
"""Generate references/COMMAND-INTERACTION.md from the live registry + tests.

受版本控制的文档生成器（Skill 交付物）。每次增删命令或修改命令契约后必须重跑，
以保证《命令 ↔ Skill 交互核对清单》与注册表、测试同步：

    PYTHONPATH=src python scripts/generate_command_interaction.py

可选：--check 只校验当前文档是否为最新（用于发布前/CI），不一致时以非零码退出。

真值来源：
  - 命令契约  : src/vcenter_aiops/application/registry.py 的 COMMANDS
  - 离线测试  : tests/ 的静态扫描 + 下方 TIER_FIX 的符号级人工修正
本脚本不连接 vCenter、不写入运行状态，仅渲染 references/COMMAND-INTERACTION.md。
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vcenter_aiops.application.registry import COMMANDS  # noqa: E402
from vcenter_aiops import __version__  # noqa: E402

TEST_DIR = ROOT / "tests"
if not TEST_DIR.is_dir():
    raise SystemExit(
        "generate_command_interaction.py 必须在含 tests/ 的源码仓库根目录运行；"
        "已安装 Skill 不含测试，不能在此重生成，请在源码树执行后随发布同步文档。"
    )
TEST_TEXTS = {f.name: f.read_text(encoding="utf-8") for f in TEST_DIR.glob("test_*.py")}

# ---------------------------------------------------------------------------
# Coverage classification
# ---------------------------------------------------------------------------
# 静态扫描无法可靠识别的情况（元组词元遍历、直接调用 handler、纯逻辑反查等），
# 在此做符号级人工修正。新增命令若仅经共享执行轨或纯逻辑覆盖，应在此登记说明。
TIER_FIX = {
    "vm reset": ("shared", [], "经 Engine+Mutations 共享写轨；专属 ResetVM_Task 分支无离线用例"),
    "vm suspend": ("shared", [], "经 Engine+Mutations 共享写轨；专属 SuspendVM_Task 分支无离线用例"),
    "deploy mark-template": ("shared", [], "经 Engine+Mutations 共享写轨；专属 MarkAsTemplate 分支无离线用例"),
    "vm guest-output": ("logic", ["test_guest_transfer.py", "test_guest_processes.py"],
                        "凭 run-id 经 store.guest_run 反查只读；输出解码/标记解析由纯逻辑覆盖，无独立 CLI 字面用例"),
    "version": ("behavior", ["test_foundation.py"],
                "test_version_and_doctor_do_not_create_state 以元组词元遍历调用 version/doctor"),
    "doctor": ("behavior", ["test_foundation.py"], "同上，并断言不联网、不创建状态"),
    "plan validate": ("behavior", ["test_linked_clone_strict.py", "test_provider_routing.py"],
                      "handler plan_validate 被直接调用断言（Engine.validate 路径）"),
    "task reconcile": ("behavior", ["test_linked_clone_strict.py", "test_execution.py"],
                       "handler task_reconcile/Engine 核对路径被直接断言，不重复提交"),
    "batch power-on": ("behavior", ["test_provider_routing.py"],
                       "plans.batch_power_on 被直接调用，断言只构建固定对象计划不提交"),
    "policy inspect": ("contract", [], "静态策略视图无专属 CLI/handler 用例，仅被全量 schema/--help 基线覆盖"),
    "deploy clone-template": ("logic", ["test_template_clone.py"],
                              "Provider preflight/submit/observe/verify 全链路 + Engine request_id 去重被直接断言；"
                              "命令仅为薄 preview 包装层，未逐字走 CLI（路径字面量仅作 preflight 实参）"),
}

# ---------------------------------------------------------------------------
# Presentation tables (code-verified summaries, kept deliberately conservative)
# ---------------------------------------------------------------------------
CATEGORY_CN = {
    "local_read": "本地只读", "local_write": "本地写入", "remote_read": "远端只读",
    "remote_write": "远端写（确认执行）", "orchestration": "编排/恢复",
}
TIER_CN = {
    "behavior": "①行为级离线测试（CLI/handler 直接断言）",
    "logic": "②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）",
    "shared": "③共享执行轨（经已测试的 Engine+Mutations 轨，该动词专属 SDK 分支无离线用例）",
    "contract": "④仅注册契约基线（schema/--help 全量基线，无专属用例）",
}
EXPECTED = {
    "version": "data={version, product}；当前 version=%(ver)s。不联网、不建状态。",
    "doctor": "data.dependencies={pyVmomi,yaml 布尔}、data.data_home、data.connected=false（仅 --connect 才连接）。",
    "capabilities list": "data 含 release_stage(execution_beta)、commands[]、vsphere{6.5/6.7/7.0/8.0=not_lab_verified}、beta_note、limitations。",
    "capabilities show": "data=该叶子完整契约：input_schema(additionalProperties:false)、privileges、risk、asynchronous、provider_kind、vsphere 四版本状态。",
    "profile list": "data 为 Profile 摘要列表，只含引用不含密码。",
    "profile show": "data 为指定 Profile；password_ref 显示为引用，不回显明文。",
    "profile add": "写入 config.yaml；只接受 password_ref 引用，拒绝明文字段；返回已存配置。",
    "profile update": "字段级合并更新并回写，校验同 add。",
    "profile delete": "删除指定 Profile；不存在返回 profile_not_found。",
    "profile test": "连接并返回服务端 about 身份（instance_uuid/api_version/version/apiType），validation_status=not_lab_verified。",
    "ip reserve": "在 scope 内事务预留 IP，返回租约 token/到期；冲突被唯一约束拒绝。",
    "ip release": "按精确 lease_id 释放；非过期/不存在返回 lease_not_expired。",
    "ip list": "data.items 为租约列表（token/scope/ip/owner/expires）。",
    "ip check": "data 汇总 inventory_use + active_lease + ping 三路信号；ping 不通只标记 inconclusive，不判空闲。",
    "ip available": "仅在有正向空闲证据时 available=true，否则 false 并给 reasons/inconclusive。",
    "ip expire": "data.items 列已过期租约；仅 --apply + 精确 lease_id 才释放。",
    "alarm reset": "先预览返回 awaiting_confirmation 并绑定精确告警 key 集合；apply 后 data={reset,command,requested_count}；6.5 返回 capability_unsupported；提交前范围扩大返回 plan_stale。",
}
PLACE = {
    "vm_id": "vm-101", "host_id": "host-21", "cluster_id": "domain-c7", "datastore_id": "datastore-30",
    "entity_id": "vm-101", "pool_id": "resgroup-9", "folder_id": "group-v4", "snapshot_id": "snapshot-2",
    "alarm_id": "alarm-12", "file": "./out.json", "name": "demo-vm", "new_name": "demo-vm-renamed",
    "snapshot_name": "snap-before", "address": "10.10.50.21", "scope": "vlan50", "owner": "ops",
    "guest_username": "root", "credential_ref": "env:GUEST_PASS", "guest_path": "/var/log/app.log",
    "plan_id": "<plan-id>", "operation_id": "<op-id>", "command_path": "alarm reset",
    "lease_id": "<lease-id>", "spec_file": "./customize.yaml", "ova_file": "./appliance.ova",
    "ovf_file": "./appliance.ovf", "entity_type": "vm", "event_type": "VmPoweredOnEvent",
    "path": "/iso/setup.iso", "hostname": "newhost", "run_parent": "/tmp",
    "python_path": "/usr/bin/python3", "password_ref": "env:VC_PASSWORD",
}
SKIP_FLAGS = {"confirm", "confirm_destruction", "wait", "dry_run", "request_id", "connect",
              "insecure", "recursive", "apply", "overwrite"}
NO_PROFILE_EXACT = {
    "version", "doctor", "capabilities list", "capabilities show", "profile list", "profile show",
    "profile add", "profile update", "profile delete", "secret set", "secret rotate",
    "secret list", "secret delete", "ip reserve", "ip release", "ip list", "ip expire",
}
LOGIC_SYMBOLS = {
    "ip": [r"IpSignals", r"ping_probe", r"\.leases\(", r"expire_release", r"\.release\("],
    "plan": [r"\bEngine\b", r"plan_", r"reconcile", r"compensation", r"rollback", r"\.archive\("],
    "task": [r"\bEngine\b", r"operations", r"reconcile", r"cancel", r"task_"],
    "secret": [r"SecretVault", r"\.rotate\(", r"\.resolve\("],
    "history": [r"\bHistory\b", r"history"],
    "preset": [r"\bPresets\b", r"preset"],
    "batch": [r"batch", r"power_on", r"power_off", r"shutdown", r"\breset\b"],
}
READ_SYMBOLS = {
    "events": [r"\bevents\b", r"ops\."], "quota": [r"quota", r"\bcapacity\b"],
    "inventory": [r"\bInventory\b"], "vm": [r"\bInventory\b", r"\bReads\("],
    "template": [r"\btemplate\b", r"\bReads\("], "host": [r"\bInventory\b", r"\bReads\("],
    "cluster": [r"\bInventory\b"], "datastore": [r"\bInventory\b", r"search_"],
    "alarm": [r"\balarms\b", r"triggered"],
}
SPECIFIC_LOGIC = {
    "vm snapshot-list": [r"\.snapshots\("], "vm tools-status": [r"\.tools\("],
    "vm wait-tools": [r"wait", r"tools"], "deploy mark-template": [r"MarkAsTemplate", r"template"],
    "vm guest-exec-output": [r"capture_output", r"read_output", r"run_wrapper"],
    "vm guest-output": [r"fetch_output", r"guest_run"],
    "vm guest-download": [r"download_file", r"download\("],
    "vm guest-upload": [r"upload_file", r"upload\("],
    "audit": [r"\baudit\b", r"Audit"],
}

DOMAIN_ORDER = ["version", "doctor", "capabilities", "profile", "ip", "plan", "audit",
                "inventory", "events", "quota", "vm", "template", "deploy", "host",
                "cluster", "datastore", "alarm", "cache", "task", "batch", "secret",
                "history", "preset", "policy"]


def cmd_dict(c):
    return {
        "path": c.path, "operation_id": c.operation_id, "category": c.category,
        "description": c.description, "handler_ref": c.handler_ref,
        "parameters": [{"name": p.name, "type": p.type, "required": p.required,
                        "positional": p.positional, "has_default": p.default is not None,
                        "default": None if p.default is None else p.default,
                        "choices": list(p.choices), "minimum": p.minimum, "maximum": p.maximum,
                        "item_variants": len(p.item_variants), "description": p.description}
                       for p in c.parameters],
        "privileges": list(c.privileges), "risk": c.risk, "asynchronous": c.asynchronous,
        "mcp": c.mcp, "provider_kind": c.provider_kind,
    }


def needs_profile(path):
    if path in NO_PROFILE_EXACT:
        return False
    if path.split(" ", 1)[0] in ("version", "doctor", "capabilities", "profile", "secret", "policy"):
        return False
    return True


def cli_example(c):
    d = cmd_dict(c)
    toks = (["vcenter-aiops", "--profile", "lab"] if needs_profile(d["path"]) else ["vcenter-aiops"]) + d["path"].split(" ")
    shown = 0
    for p in d["parameters"]:
        if p["name"] in SKIP_FLAGS:
            continue
        if shown >= 4:
            break
        n, flag = p["name"], "--" + p["name"].replace("_", "-")
        if p["positional"]:
            toks.append(PLACE.get(n, "<%s>" % n))
        elif p["type"] == "boolean":
            toks.append(flag)
        elif p["type"] == "array":
            val = '\'["red","yellow"]\'' if n == "statuses" else ('\'["vm-1","vm-2"]\'' if n == "vm_ids" else "'[]'")
            toks += [flag, val]
        elif p["type"] == "object":
            toks += [flag, '\'{"key":"value"}\'']
        elif p["choices"]:
            toks += [flag, str(p["choices"][0])]
        elif p["type"] == "integer":
            sample = p["minimum"] if p["minimum"] not in (None, 0) else (p["default"] if p["has_default"] else 1)
            toks += [flag, str(sample)]
        else:
            toks += [flag, PLACE.get(n, "<%s>" % n)]
        shown += 1
    return " ".join(toks)


def param_rows(c):
    rows = []
    for p in cmd_dict(c)["parameters"]:
        default = "（必填）" if p["required"] else ("无默认" if not p["has_default"] else "`%s`" % json.dumps(p["default"], ensure_ascii=False))
        cons = []
        if p["choices"]:
            cons.append("枚举 " + "/".join(map(str, p["choices"])))
        if p["minimum"] is not None:
            cons.append("≥%s" % p["minimum"])
        if p["maximum"] is not None:
            cons.append("≤%s" % p["maximum"])
        if p["item_variants"]:
            cons.append("数组项 %d 种唯一形态" % p["item_variants"])
        rows.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            p["name"], p["type"], "是" if p["required"] else "否",
            "位置参数" if p["positional"] else "选项", default, "；".join(cons) or "—",
            (p["description"] or "").replace("|", "\\|")))
    return "\n".join(rows) if rows else "| _（无参数）_ | | | | | | |"


def expected_for(c):
    d = cmd_dict(c)
    if d["path"] in EXPECTED:
        return EXPECTED[d["path"]] % {"ver": __version__} if "%(ver)s" in EXPECTED[d["path"]] else EXPECTED[d["path"]]
    cat = d["category"]
    if cat == "remote_write":
        return ("远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；"
                "`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。")
    if cat == "remote_read":
        return "只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。"
    if cat == "orchestration":
        return "编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。"
    if cat == "local_write":
        return "本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。"
    return "本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。"


def classify(c):
    d = cmd_dict(c)
    path, op, fn, cat = d["path"], d["operation_id"], d["handler_ref"].split(":")[1], d["category"]
    toks = path.split(" ")
    if len(toks) == 1:
        pat = re.compile(r'(?:main\(\[|self\.cli\(|\bcli\()[\s\S]{0,48}["\x27]' + re.escape(toks[0]) + r'["\x27]')
        direct = sorted(n for n, t in TEST_TEXTS.items() if pat.search(t))
    else:
        q = r"(?:\"|')"
        seq = re.compile(r"\s*,\s*".join(q + re.escape(x) + q for x in toks))
        fnrx = re.compile(r"\b" + re.escape(fn) + r"\b")
        direct = sorted(n for n, t in TEST_TEXTS.items() if (path in t) or (op in t) or seq.search(t) or fnrx.search(t))
    if direct:
        return "behavior", direct, None
    group = path.split(" ", 1)[0]
    symbols = SPECIFIC_LOGIC.get(path) or LOGIC_SYMBOLS.get(group) or READ_SYMBOLS.get(group) or []
    indirect = sorted(n for n, t in TEST_TEXTS.items() if any(re.search(p, t) for p in symbols))
    if indirect:
        return "logic", indirect, None
    return ("shared" if cat == "remote_write" else "contract"), [], None


def render():
    cmds = [cmd_dict(c) for c in COMMANDS]
    L = []
    A = L.append
    A("# 命令 ↔ Skill 交互核对清单（vcenter-aiops %s）\n" % __version__)
    A("> **受版本控制的 Skill 交付物**。真值来源：`src/vcenter_aiops/application/registry.py` 的 `COMMANDS`"
      "（运行时实测 **%d** 条）。本文档由 `scripts/generate_command_interaction.py` 从注册表与 `tests/` 自动生成；"
      "**每次增删命令或修改命令契约/参数后必须重跑该脚本并随版本一起提交**，不要手工编辑正文。"
      "CLI 示例值均为占位，不代表真实环境。\n" % len(cmds))

    A("## 0. 统一交互契约\n")
    A("**入口**：`./run.sh …`（macOS/linux）或 `run.bat …`（Windows）；wheel 安装后为 `vcenter-aiops …`。"
      "全局参数位于领域命令之前：`--profile <名>`、`--format json|table`（默认 json）、`--timeout 1..3600`。\n")
    A("**发送给 Skill 的完整请求 = 全局参数 + 领域 + 动词 + 叶子参数**。示例 `vm power-on --vm-id vm-101 --dry-run`，"
      "其内部参数对象（handler 实际收到的 `params`，键名为下划线形式）：")
    A("```json")
    A(json.dumps({"_global": {"profile": "lab", "format": "json", "timeout": 30},
                  "command": "vm power-on", "params": {"vm_id": "vm-101", "dry_run": True}},
                 ensure_ascii=False, indent=2))
    A("```")
    A("**统一响应信封**：")
    A("```json")
    A(json.dumps({"schema_version": "1",
                  "status": "succeeded|awaiting_confirmation|failed|partial|reconciliation_required",
                  "data": {}, "operation_id": None, "target": None,
                  "warnings": [], "error": None, "next_action": None}, ensure_ascii=False, indent=2))
    A("```")
    A("**退出码**：0 成功 / 2 参数错误 / 3 依赖·配置·连接 / 4 前置·身份 / 5 失败·部分 / 6 需核对。"
      "远端写命令**不直接提交**：先返回 `awaiting_confirmation`，再用 `plan apply <id> --confirm <digest>` 执行；"
      "不可逆操作另需 `--confirm-destruction`。\n")

    A("**离线测试状态分级**：")
    A("- ① **行为级**：测试以 CLI 词元/命令字面量/精确 handler 名直接驱动并断言。")
    A("- ② **逻辑级**：底层纯函数或 Provider 方法被直接单测，命令薄包装层未逐字走 CLI（覆盖等价逻辑）。")
    A("- ③ **共享执行轨**：经已被测试的 Engine+Mutations 写轨，但该动词专属 SDK 分支无离线用例。")
    A("- ④ **仅契约基线**：仅被全量 schema/`--help` 基线覆盖。")
    A("- 所有远端命令的 6.5/6.7/7.0/8.0 兼容性在 capabilities 中均为 `not_lab_verified`，离线测试**不等于实机验收**。\n")

    tier_count = Counter()
    resolved = {}
    for d in cmds:
        if d["path"] in TIER_FIX:
            t, f, note = TIER_FIX[d["path"]]
        else:
            t, f, note = classify(next(c for c in COMMANDS if c.path == d["path"]))
        resolved[d["path"]] = (t, f, note)
        tier_count[t] += 1
    A("**覆盖汇总**：总 %d = ①行为级 **%d** + ②逻辑级 **%d** + ③共享轨 **%d** + ④仅契约 **%d**。\n" % (
        len(cmds), tier_count["behavior"], tier_count["logic"], tier_count["shared"], tier_count["contract"]))
    A("> 复核方法：运行 `vcenter-aiops capabilities list`（机器契约）或 `vcenter-aiops capabilities show \"领域 动词\"`（单条 schema）；"
      "离线测试用 `python -m unittest discover -s tests -p \"test_*.py\" < /dev/null`。"
      "再生成/校验本文档：`PYTHONPATH=src python scripts/generate_command_interaction.py`（加 `--check` 仅校验是否最新）。"
      "实机验收时建议优先覆盖 ③ 的 %d 条与 ② 中的新增写命令。\n" % tier_count["shared"])

    def group_of(path):
        return path.split(" ", 1)[0]

    cmds_sorted = sorted(cmds, key=lambda d: (
        DOMAIN_ORDER.index(group_of(d["path"])) if group_of(d["path"]) in DOMAIN_ORDER else 99, d["path"]))
    current = None
    for d in cmds_sorted:
        g = group_of(d["path"])
        if g != current:
            current = g
            A("\n---\n")
            A("## 领域 `%s`\n" % g)
        t0, f0, note = resolved[d["path"]]
        priv = ", ".join("`%s`" % x for x in d["privileges"]) if d["privileges"] else "—"
        A("### `%s`  ·  %s" % (d["path"], CATEGORY_CN[d["category"]]))
        A("- **operation_id**：`%s`" % d["operation_id"])
        A("- **handler**：`%s`　|　**provider_kind**：`%s`　|　**风险**：%s　|　**异步**：%s　|　**MCP 暴露**：%s" % (
            d["handler_ref"], d["provider_kind"], d["risk"], "是" if d["asynchronous"] else "否", "是" if d["mcp"] else "否"))
        A("- **所需特权**：%s" % priv)
        A("- **说明**：%s" % d["description"])
        A("- **输入参数**：")
        A("| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |")
        A("|---|---|---|---|---|---|---|")
        A(param_rows(next(c for c in COMMANDS if c.path == d["path"])))
        A("- **触发方式（CLI，占位值）**：")
        A("```text")
        A(cli_example(next(c for c in COMMANDS if c.path == d["path"])))
        A("```")
        A("- **预期结果**：%s" % expected_for(next(c for c in COMMANDS if c.path == d["path"])))
        A("- **离线测试状态**：%s" % TIER_CN[t0])
        if f0:
            A("  - 覆盖文件：%s" % ", ".join("`%s`" % x for x in f0))
        if note:
            A("  - 备注：%s" % note)
        if d["category"] in ("remote_read", "remote_write", "orchestration"):
            A("- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。")
        A("")
    return "\n".join(L) + "\n"


def main():
    parser = argparse.ArgumentParser(description="生成/校验《命令 ↔ Skill 交互核对清单》")
    parser.add_argument("--check", action="store_true", help="仅校验文档是否为最新，不写文件")
    args = parser.parse_args()
    content = render()
    target = ROOT / "references" / "COMMAND-INTERACTION.md"
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != content:
            print("COMMAND-INTERACTION.md 与注册表/测试不一致，请重跑 generate_command_interaction.py", file=sys.stderr)
            return 1
        print("COMMAND-INTERACTION.md 已是最新（%d 条命令）" % len(COMMANDS))
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print("written:", target.relative_to(ROOT), "commands:", len(COMMANDS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

