---
name: vcenter-ops
description: "Operate VMware vCenter VMs: inventory, clone, power, snapshot, migrate, delete, audit, quota, metrics, RBAC, and lifecycle automation."
metadata:
  version: 1.5.0
  entrypoint: scripts/handler.py
  schema_ref: references/SCHEMA.md
  action_matrix_ref: references/ACTION-MATRIX.md
---

# vCenter Ops

Use for VMware vCenter operations: inventory/query, clone/delivery, power, snapshot, reconfigure, guest command, migrate, datastore/template, batch, TTL, approval, audit, quota, metrics, recommendation, anomaly/forecast, RBAC, secrets, change windows, webhooks, IP pool, and lifecycle automation.

## Route banner

First line when triggered:

- Normal: `🛡️ 已自动识别为 vCenter 操作，已路由到 vcenter-ops Skill 执行。`
- Delete/destroy: `🚨【vCenter 高风险操作拦截】检测到删除/销毁类操作，该行为不可恢复。必须通过 vcenter-ops Skill 并经过确认流程执行。系统已自动进行安全路由。`

## Entry

All paths in this Skill are **relative to the Skill root** (the directory that contains this `SKILL.md`).
The AI agent runtime is expected to `cd` into the Skill root before invoking commands.

```bash
# Portable form — works on any platform that mounts the Skill into cwd
python3 scripts/handler.py --action <action> [options]
```

### Platform install paths (reference only)

| Platform | Skill root |
| --- | --- |
| Codex (`~/.codex`) | `~/.codex/skills/vcenter-ops` |
| Claude Code | `~/.claude/skills/vcenter-ops` or `<project>/.claude/skills/vcenter-ops` |
| openclaw | `/root/.openclaw/workspace-infraops/skills/vcenter-ops` |
| qclaw | `~/.qclaw/skills/vcenter-ops` |
| hermes | `~/.hermes/skills/vcenter-ops` |
| OpenCode | `~/.opencode/skills/vcenter-ops` or `<project>/.opencode/skills/vcenter-ops` |
| Generic / other agents | any directory containing this `SKILL.md`; export `SKILL_DIR` to it |

Cross-shell fallback if the runtime does not auto-cd:

```bash
# Bash / Zsh (macOS, Linux)
cd "${SKILL_DIR:-$(dirname "$0")}" && python3 scripts/handler.py --action <action> [options]
```

```powershell
# PowerShell (Windows)
Set-Location $env:SKILL_DIR; python scripts\handler.py --action <action> [options]
```

## Load when needed

- Action list/examples: `references/ACTION-MATRIX.md`
- Full CLI schema: `references/SCHEMA.md`
- Clone preflight flow: `references/CLONE-FLOW.md`
- Permission/safety: `references/PERMISSION-SYSTEM.md`, `references/SAFETY-GATE.md`
- Cache strategy: `references/CACHE-STRATEGY.md`
- User guide: `references/USER-GUIDE.md`
- Production runbook: `references/OPS-RUNBOOK.md`
- Version/changes: `references/VERSION-MATRIX.md`, `references/CHANGELOG.md`

## First connection

1. Check `config.yaml` for vCenter host/user/password_ref.
2. Password is read from `.env` or encrypted secret store; never print secrets.
3. If missing, ask once for host/user/password, write safely, then confirm.

## Naming rule

VM name format: `IP-自定义名称`. If user only gives a custom name, auto-prefix the selected IP.

## Cache rule

- First inventory: `python3 scripts/cache_manager.py --refresh`.
- Reuse cache by section unless user says “刷新”.
- Cache docs: `references/CACHE-STRATEGY.md`.

## Clone workflow

Do not skip preflight.

1. Inventory/preflight: refresh cache and summarize resources.
2. Parameter selection: template, cluster, datastore, network, name, CPU, memory, disk, IP, mask, gateway.
3. IP validation: ping unreachable + not in vCenter VM IPs + not matched by VM-name IP regex; user-specified IP must be checked.
4. Confirmation: show final plan, then execute only after `Y`.
5. Execute: `clone_vm`, optional power on, wait for VMware Tools/IP, then `get_vm` verify.

Detailed flow: `references/CLONE-FLOW.md`.

## Permission levels

- 🔵 Query/low-risk: inventory, get VM, list snapshots, export, preset/history, quota/events.
- 🟡 Sensitive change: power, guest command, migrate, batch, TTL cleanup, webhook/secret/RBAC/config changes.
- 🔴 Delete/destroy: delete VM or irreversible cleanup.

## Delete safety rules

Hard rules, no exception:

1. Two confirmations are required.
2. Reject “delete all / 清空 / 通配符删除 / 条件批量删除”.
3. Require exact VM name or exact IP.
4. Prefer approval flow when enabled.
5. Record audit evidence before and after execution.

Permission details: `references/PERMISSION-SYSTEM.md`.

## Common commands

```bash
python3 scripts/handler.py --help
python3 scripts/handler.py --action list_all
python3 scripts/handler.py --action get_vm --hostname "xxx"
python3 scripts/handler.py --action preset
python3 scripts/handler.py --action export --export_format html --output /tmp/vms.html
python3 scripts/healthcheck.py
pytest -q
```

## Validation after edits

```bash
python3 -m py_compile scripts/*.py
pytest -q
python3 scripts/handler.py --help >/tmp/vcenter-ops-help.txt
python3 scripts/healthcheck.py
```
