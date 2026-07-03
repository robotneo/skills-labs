# S1-S5 安全强制化

## S1 Preflight Gate

```bash
python3 scripts/preflight_gate.py --action delete_vm --target '<vm>' --actor yanghua --role admin --evidence '<evidence_dir>' --token '<token>'
```

只做校验，不执行目标操作。

## S2 删除前证据包

```bash
python3 scripts/evidence_collector.py --action delete_vm --target '<vm>' --actor yanghua
```

输出：

```text
reports/evidence/delete_vm/<vm>/<timestamp>/
```

包含：`meta.json`、`vm.json`、`snapshots.json`、`events.json`、`asset.json`、`monitoring.json`、`rollback.md`、`summary.json`。

## S3 密钥安全加强

```bash
python3 scripts/secret_audit.py
python3 scripts/secret_audit.py --fix
```

要求 `.env`、`data/.master_key`、`data/secrets.json` 权限为 `600`。

## S4 危险操作 Token 化

```bash
python3 scripts/danger_token.py --action create --actor yanghua --target-action delete_vm --target '<vm>'
python3 scripts/danger_token.py --action verify --actor yanghua --target-action delete_vm --target '<vm>' --token '<token>'
```

Token 绑定 actor + action + target，默认 300 秒过期，验证后即使用。

## S5 批量限流和保护

```bash
python3 scripts/batch_guard.py --action batch_clone --count 5 --role operator --workers 2
```

默认：

```text
operator 最大 5
admin 最大 20
delete_vm 禁止批量
workers 默认最多 2
failure_rate >= 30% 熔断
```

## 高危删除推荐流程

```bash
EV=$(python3 scripts/evidence_collector.py --action delete_vm --target '<vm>' --actor yanghua | jq -r .evidence_dir)
TOKEN=$(python3 scripts/danger_token.py --action create --actor yanghua --target-action delete_vm --target '<vm>' | jq -r .token)
python3 scripts/preflight_gate.py --action delete_vm --target '<vm>' --actor yanghua --role admin --evidence "$EV" --token "$TOKEN"
```

通过后才允许进入真实删除确认流程。
