# 命令 ↔ Skill 交互核对清单（vcenter-aiops 3.0.0b4）

> **受版本控制的 Skill 交付物**。真值来源：`src/vcenter_aiops/application/registry.py` 的 `COMMANDS`（运行时实测 **112** 条）。本文档由 `scripts/generate_command_interaction.py` 从注册表与 `tests/` 自动生成；**每次增删命令或修改命令契约/参数后必须重跑该脚本并随版本一起提交**，不要手工编辑正文。CLI 示例值均为占位，不代表真实环境。

## 0. 统一交互契约

**入口**：`./run.sh …`（macOS/linux）或 `run.bat …`（Windows）；wheel 安装后为 `vcenter-aiops …`。全局参数位于领域命令之前：`--profile <名>`、`--format json|table`（默认 json）、`--timeout 1..3600`。

**发送给 Skill 的完整请求 = 全局参数 + 领域 + 动词 + 叶子参数**。示例 `vm power-on --vm-id vm-101 --dry-run`，其内部参数对象（handler 实际收到的 `params`，键名为下划线形式）：
```json
{
  "_global": {
    "profile": "lab",
    "format": "json",
    "timeout": 30
  },
  "command": "vm power-on",
  "params": {
    "vm_id": "vm-101",
    "dry_run": true
  }
}
```
**统一响应信封**：
```json
{
  "schema_version": "1",
  "status": "succeeded|awaiting_confirmation|failed|partial|reconciliation_required",
  "data": {},
  "operation_id": null,
  "target": null,
  "warnings": [],
  "error": null,
  "next_action": null
}
```
**退出码**：0 成功 / 2 参数错误 / 3 依赖·配置·连接 / 4 前置·身份 / 5 失败·部分 / 6 需核对。远端写命令**不直接提交**：先返回 `awaiting_confirmation`，再用 `plan apply <id> --confirm <digest>` 执行；不可逆操作另需 `--confirm-destruction`。

**离线测试状态分级**：
- ① **行为级**：测试以 CLI 词元/命令字面量/精确 handler 名直接驱动并断言。
- ② **逻辑级**：底层纯函数或 Provider 方法被直接单测，命令薄包装层未逐字走 CLI（覆盖等价逻辑）。
- ③ **共享执行轨**：经已被测试的 Engine+Mutations 写轨，但该动词专属 SDK 分支无离线用例。
- ④ **仅契约基线**：仅被全量 schema/`--help` 基线覆盖。
- 所有远端命令的 6.5/6.7/7.0/8.0 兼容性在 capabilities 中均为 `not_lab_verified`，离线测试**不等于实机验收**。

**覆盖汇总**：总 112 = ①行为级 **74** + ②逻辑级 **34** + ③共享轨 **3** + ④仅契约 **1**。

> 复核方法：运行 `vcenter-aiops capabilities list`（机器契约）或 `vcenter-aiops capabilities show "领域 动词"`（单条 schema）；离线测试用 `python -m unittest discover -s tests -p "test_*.py" < /dev/null`。再生成/校验本文档：`PYTHONPATH=src python scripts/generate_command_interaction.py`（加 `--check` 仅校验是否最新）。实机验收时建议优先覆盖 ③ 的 3 条与 ② 中的新增写命令。


---

## 领域 `version`

### `version`  ·  本地只读
- **operation_id**：`version`
- **handler**：`application.commands.local:version`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：查看开发版本
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| _（无参数）_ | | | | | | |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops version
```
- **预期结果**：data={version, product}；当前 version=3.0.0b4。不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`
  - 备注：test_version_and_doctor_do_not_create_state 以元组词元遍历调用 version/doctor


---

## 领域 `doctor`

### `doctor`  ·  本地只读
- **operation_id**：`doctor`
- **handler**：`application.commands.local:doctor`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：检查本机依赖，显式 --connect 才连接
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| connect | boolean | 否 | 选项 | `false` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops doctor
```
- **预期结果**：data.dependencies={pyVmomi,yaml 布尔}、data.data_home、data.connected=false（仅 --connect 才连接）。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`
  - 备注：同上，并断言不联网、不创建状态


---

## 领域 `capabilities`

### `capabilities list`  ·  本地只读
- **operation_id**：`capabilities.list`
- **handler**：`application.commands.local:capabilities_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：查看实现和版本验证状态
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| _（无参数）_ | | | | | | |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops capabilities list
```
- **预期结果**：data 含 release_stage(execution_beta)、commands[]、vsphere{6.5/6.7/7.0/8.0=not_lab_verified}、beta_note、limitations。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`

### `capabilities show`  ·  本地只读
- **operation_id**：`capabilities.show`
- **handler**：`application.commands.local:capabilities_show`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：查看叶子参数 schema 与风险
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| command_path | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops capabilities show alarm reset
```
- **预期结果**：data=该叶子完整契约：input_schema(additionalProperties:false)、privileges、risk、asynchronous、provider_kind、vsphere 四版本状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_contracts.py`


---

## 领域 `profile`

### `profile add`  ·  本地写入
- **operation_id**：`profile.add`
- **handler**：`application.commands.local:profile_add`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：添加连接配置
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — |  |
| host | string | 是 | 选项 | （必填） | — |  |
| user | string | 是 | 选项 | （必填） | — |  |
| password_ref | string | 是 | 选项 | （必填） | — |  |
| port | integer | 否 | 选项 | `443` | ≥1；≤65535 |  |
| ca_file | string | 否 | 选项 | 无默认 | — |  |
| insecure | boolean | 否 | 选项 | `false` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops profile add demo-vm --host <host> --user <user> --password-ref env:VC_PASSWORD
```
- **预期结果**：写入 config.yaml；只接受 password_ref 引用，拒绝明文字段；返回已存配置。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`

### `profile delete`  ·  本地写入
- **operation_id**：`profile.delete`
- **handler**：`application.commands.local:profile_delete`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：删除本地配置
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops profile delete demo-vm
```
- **预期结果**：删除指定 Profile；不存在返回 profile_not_found。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`

### `profile list`  ·  本地只读
- **operation_id**：`profile.list`
- **handler**：`application.commands.local:profile_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：列出连接配置
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| _（无参数）_ | | | | | | |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops profile list
```
- **预期结果**：data 为 Profile 摘要列表，只含引用不含密码。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`

### `profile show`  ·  本地只读
- **operation_id**：`profile.show`
- **handler**：`application.commands.local:profile_show`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：查看配置，不显示密码
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops profile show demo-vm
```
- **预期结果**：data 为指定 Profile；password_ref 显示为引用，不回显明文。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`

### `profile test`  ·  远端只读
- **operation_id**：`profile.test`
- **handler**：`application.commands.queries:profile_test`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：验证连接及服务端身份
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| _（无参数）_ | | | | | | |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops profile test
```
- **预期结果**：连接并返回服务端 about 身份（instance_uuid/api_version/version/apiType），validation_status=not_lab_verified。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_secrets.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `profile update`  ·  本地写入
- **operation_id**：`profile.update`
- **handler**：`application.commands.local:profile_update`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：只更新指定字段
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — |  |
| host | string | 否 | 选项 | 无默认 | — |  |
| user | string | 否 | 选项 | 无默认 | — |  |
| password_ref | string | 否 | 选项 | 无默认 | — |  |
| port | integer | 否 | 选项 | 无默认 | ≥1；≤65535 |  |
| ca_file | string | 否 | 选项 | 无默认 | — |  |
| insecure | boolean | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops profile update demo-vm --host <host> --user <user> --password-ref env:VC_PASSWORD
```
- **预期结果**：字段级合并更新并回写，校验同 add。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_contracts.py`


---

## 领域 `ip`

### `ip available`  ·  远端只读
- **operation_id**：`ip.available`
- **handler**：`application.commands.queries:ip_available`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：仅在有正向空闲证据时返回可用，否则不确定，不自动分配
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| address | string | 是 | 选项 | （必填） | — |  |
| scope | string | 是 | 选项 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab ip available --address 10.10.50.21 --scope vlan50
```
- **预期结果**：仅在有正向空闲证据时 available=true，否则 false 并给 reasons/inconclusive。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_foundation.py`, `test_ip_signals.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `ip check`  ·  远端只读
- **operation_id**：`ip.check`
- **handler**：`application.commands.queries:ip_check`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：汇总资产占用、本地租约与 ping 三路信号；ping 不通不判空闲
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| address | string | 是 | 选项 | （必填） | — |  |
| scope | string | 是 | 选项 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab ip check --address 10.10.50.21 --scope vlan50
```
- **预期结果**：data 汇总 inventory_use + active_lease + ping 三路信号；ping 不通只标记 inconclusive，不判空闲。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_foundation.py`, `test_ip_signals.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `ip expire`  ·  本地只读
- **operation_id**：`ip.expire`
- **handler**：`application.commands.local:ip_expire`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：列出过期租约；--apply 加精确租约 ID 才释放
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| apply | boolean | 否 | 选项 | `false` | — |  |
| lease_id | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops ip expire --lease-id <lease-id>
```
- **预期结果**：data.items 列已过期租约；仅 --apply + 精确 lease_id 才释放。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_foundation.py`, `test_ip_signals.py`

### `ip list`  ·  本地只读
- **operation_id**：`ip.list`
- **handler**：`application.commands.local:ip_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：列出租约
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| scope | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops ip list --scope vlan50
```
- **预期结果**：data.items 为租约列表（token/scope/ip/owner/expires）。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_foundation.py`, `test_ip_signals.py`

### `ip release`  ·  本地写入
- **operation_id**：`ip.release`
- **handler**：`application.commands.local:ip_release`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：释放精确租约
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| lease_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops ip release <lease-id>
```
- **预期结果**：按精确 lease_id 释放；非过期/不存在返回 lease_not_expired。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_foundation.py`, `test_ip_signals.py`

### `ip reserve`  ·  本地写入
- **operation_id**：`ip.reserve`
- **handler**：`application.commands.local:ip_reserve`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：事务预留网络作用域内 IP
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| scope | string | 是 | 选项 | （必填） | — |  |
| ip | string | 是 | 选项 | （必填） | — |  |
| owner | string | 是 | 选项 | （必填） | — |  |
| minutes | integer | 否 | 选项 | 无默认 | ≥1 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops ip reserve --scope vlan50 --ip <ip> --owner ops --minutes 1
```
- **预期结果**：在 scope 内事务预留 IP，返回租约 token/到期；冲突被唯一约束拒绝。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_contracts.py`


---

## 领域 `plan`

### `plan apply`  ·  编排/恢复
- **operation_id**：`plan.apply`
- **handler**：`application.commands.changes:plan_apply`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：确认并执行固定计划
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| plan_id | string | 是 | 位置参数 | （必填） | — |  |
| confirm | string | 否 | 选项 | 无默认 | — |  |
| confirm_destruction | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan apply <plan-id>
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_guest_processes.py`, `test_linked_clone_strict.py`, `test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `plan archive`  ·  本地写入
- **operation_id**：`plan.archive`
- **handler**：`application.commands.plans:plan_archive`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：归档已结束计划，保留证据
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| plan_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan archive <plan-id>
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_cluster_lifecycle.py`, `test_enrollment_unavailable.py`, `test_execution.py`, `test_foundation.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_plans.py`, `test_provider_routing.py`, `test_search_recovery.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`

### `plan create`  ·  编排/恢复
- **operation_id**：`plan.create`
- **handler**：`application.commands.plans:plan_create`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：从声明式文件预览固定计划
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| file | string | 是 | 选项 | （必填） | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan create --file ./out.json
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `plan list`  ·  本地只读
- **operation_id**：`plan.list`
- **handler**：`application.commands.local:plan_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：列出计划
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| _（无参数）_ | | | | | | |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan list
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_cluster_lifecycle.py`, `test_enrollment_unavailable.py`, `test_execution.py`, `test_foundation.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_plans.py`, `test_provider_routing.py`, `test_search_recovery.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`

### `plan reconcile`  ·  远端只读
- **operation_id**：`plan.reconcile`
- **handler**：`application.commands.changes:plan_reconcile`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：核对原任务，不重复提交
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| plan_id | string | 是 | 位置参数 | （必填） | — |  |
| wait | boolean | 否 | 选项 | `false` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan reconcile <plan-id>
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_cluster_lifecycle.py`, `test_enrollment_unavailable.py`, `test_execution.py`, `test_foundation.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_plans.py`, `test_provider_routing.py`, `test_search_recovery.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `plan rollback`  ·  编排/恢复
- **operation_id**：`plan.rollback`
- **handler**：`application.commands.plans:plan_rollback`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：预览可执行补偿，明确不能恢复的步骤
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| plan_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan rollback <plan-id>
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_cluster_lifecycle.py`, `test_enrollment_unavailable.py`, `test_execution.py`, `test_foundation.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_plans.py`, `test_provider_routing.py`, `test_search_recovery.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `plan show`  ·  本地只读
- **operation_id**：`plan.show`
- **handler**：`application.commands.local:plan_show`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：查看计划及不可变摘要
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| plan_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan show <plan-id>
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_cluster_lifecycle.py`, `test_enrollment_unavailable.py`, `test_execution.py`, `test_foundation.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_plans.py`, `test_provider_routing.py`, `test_search_recovery.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`

### `plan validate`  ·  远端只读
- **operation_id**：`plan.validate`
- **handler**：`application.commands.plans:plan_validate`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：只核对前提，不执行
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| plan_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab plan validate <plan-id>
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_linked_clone_strict.py`, `test_provider_routing.py`
  - 备注：handler plan_validate 被直接调用断言（Engine.validate 路径）
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `audit`

### `audit export`  ·  本地写入
- **operation_id**：`audit.export`
- **handler**：`application.commands.local:audit_export`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：导出脱敏 JSON 证据，拒绝覆盖已有文件
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| file | string | 是 | 选项 | （必填） | — |  |
| limit | integer | 否 | 选项 | `10000` | ≥1；≤10000 |  |
| after_id | integer | 否 | 选项 | `0` | ≥0 |  |
| snapshot_max_id | integer | 否 | 选项 | 无默认 | ≥0 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab audit export --file ./out.json --limit 1 --after-id 0 --snapshot-max-id 1
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_audit.py`

### `audit list`  ·  本地只读
- **operation_id**：`audit.list`
- **handler**：`application.commands.local:audit_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：分页查询脱敏审计事件，不连接远端
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
| after_id | integer | 否 | 选项 | `0` | ≥0 |  |
| snapshot_max_id | integer | 否 | 选项 | 无默认 | ≥0 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab audit list --limit 1 --after-id 0 --snapshot-max-id 1
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_audit.py`


---

## 领域 `inventory`

### `inventory export`  ·  远端只读
- **operation_id**：`inventory.export`
- **handler**：`application.commands.queries:inventory_export`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：导出资产到新文件，不覆盖已有文件；json/csv，外部字段转义
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| file | string | 是 | 选项 | （必填） | — |  |
| kind | string | 否 | 选项 | `"vm"` | 枚举 vm/host/cluster/datastore |  |
| format | string | 否 | 选项 | `"json"` | 枚举 json/csv |  |
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab inventory export --file ./out.json --kind vm --format json --limit 1
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_cache.py`, `test_foundation.py`, `test_membership.py`, `test_provider.py`, `test_real_type_contracts.py`, `test_vm_creation.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `inventory list`  ·  远端只读
- **operation_id**：`inventory.list`
- **handler**：`application.commands.queries:inventory_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：批量读取资产
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
| kind | string | 否 | 选项 | `"vm"` | 枚举 vm/host/cluster/datastore |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab inventory list --limit 1 --kind vm
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_provider.py`, `test_templates_linked.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `events`

### `events list`  ·  远端只读
- **operation_id**：`events.list`
- **handler**：`application.commands.queries:events_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：按精确对象/时间/类型查询事件，不执行变更
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 否 | 选项 | 无默认 | — |  |
| host_id | string | 否 | 选项 | 无默认 | — |  |
| since | string | 否 | 选项 | 无默认 | — |  |
| event_type | string | 否 | 选项 | 无默认 | — |  |
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab events list --vm-id vm-101 --host-id host-21 --since <since> --event-type VmPoweredOnEvent
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_audit.py`, `test_cache.py`, `test_cluster_lifecycle.py`, `test_contracts.py`, `test_datastore_browser.py`, `test_enrollment_unavailable.py`, `test_execution.py`, `test_foundation.py`, `test_guest_customize.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_guest_transfer.py`, `test_guest_windows.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_ip_signals.py`, `test_license_entitlements.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_operation_state.py`, `test_ops_extensions.py`, `test_ovf.py`, `test_ovf_deploy.py`, `test_ovf_lease.py`, `test_placement.py`, `test_plans.py`, `test_provider.py`, `test_provider_routing.py`, `test_read_models.py`, `test_real_type_contracts.py`, `test_search_cli.py`, `test_search_recovery.py`, `test_secrets.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `quota`

### `quota check`  ·  远端只读
- **operation_id**：`quota.check`
- **handler**：`application.commands.queries:quota_check`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：变更前容量预检，只预检不预留；缺字段返回不可用
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| cluster_id | string | 否 | 选项 | 无默认 | — |  |
| host_id | string | 否 | 选项 | 无默认 | — |  |
| datastore_id | string | 否 | 选项 | 无默认 | — |  |
| cpu | integer | 否 | 选项 | 无默认 | ≥0 |  |
| memory_gb | integer | 否 | 选项 | 无默认 | ≥0 |  |
| storage_gb | integer | 否 | 选项 | 无默认 | ≥0 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab quota check --cluster-id domain-c7 --host-id host-21 --datastore-id datastore-30 --cpu 1
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_ops_extensions.py`, `test_ovf_lease.py`, `test_real_type_contracts.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `vm`

### `vm clone`  ·  远端写（确认执行）
- **operation_id**：`vm.clone`
- **handler**：`application.commands.changes:vm_clone`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Provisioning.Clone`
- **说明**：克隆为关机 VM，不隐式预留 IP 或改网
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| pool_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| name | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm clone --vm-id vm-101 --pool-id resgroup-9 --datastore-id datastore-30 --host-id host-21
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_placement.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm create`  ·  远端写（确认执行）
- **operation_id**：`vm.create`
- **handler**：`application.commands.creation:vm_create`　|　**provider_kind**：`creation`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Inventory.Create`, `VirtualMachine.Config.AddNewDisk`, `Resource.AssignVMToPool`, `Datastore.AllocateSpace`, `Network.Assign`
- **说明**：创建关机空白 VM；容量单位 GiB，不分配 IP
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 选项 | （必填） | — |  |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| pool_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| network_id | string | 是 | 选项 | （必填） | — |  |
| guest_id | string | 是 | 选项 | （必填） | — |  |
| hardware_version | string | 是 | 选项 | （必填） | — |  |
| cpu | integer | 是 | 选项 | （必填） | ≥1 |  |
| memory_gb | integer | 是 | 选项 | （必填） | ≥1 |  |
| disk_gb | integer | 是 | 选项 | （必填） | ≥1 |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm create --name demo-vm --folder-id group-v4 --pool-id resgroup-9 --host-id host-21
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_vm_creation.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm delete`  ·  远端写（确认执行）
- **operation_id**：`vm.delete`
- **handler**：`application.commands.changes:vm_delete`　|　**provider_kind**：`vm`　|　**风险**：destructive　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Inventory.Delete`
- **说明**：严格保护：无法排除外部链接磁盘依赖时拒绝销毁；当前无全局排除证据，不能执行
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm delete --vm-id vm-101
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_execution.py`, `test_linked_clone_strict.py`, `test_plans.py`, `test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm guest-customize`  ·  远端写（确认执行）
- **operation_id**：`vm.guest_customize`
- **handler**：`application.commands.guest:guest_customize`　|　**provider_kind**：`guest`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.GuestOperations.Execute`, `VirtualMachine.GuestOperations.Query`
- **说明**：按声明式规格（hostname/IP/掩码/网关/DNS）经固定包装器对已开机 VM 来宾定制；不隐式开机，提交成功不等同来宾配置完成
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — |  |
| guest_username | string | 是 | 选项 | （必填） | — |  |
| credential_ref | string | 是 | 选项 | （必填） | — |  |
| os_family | string | 是 | 选项 | （必填） | 枚举 linux/windows |  |
| python_path | string | 是 | 选项 | （必填） | — |  |
| spec_file | string | 是 | 选项 | （必填） | — |  |
| run_parent | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm guest-customize --vm-id vm-101 --guest-username root --credential-ref env:GUEST_PASS --os-family linux
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_guest_customize.py`, `test_guest_customize_flow.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm guest-download`  ·  远端只读
- **operation_id**：`vm.guest_download`
- **handler**：`application.commands.guest:guest_download`　|　**provider_kind**：`guest`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.GuestOperations.Query`
- **说明**：从 Guest 下载单个有界文件（≤4MiB）到本地新文件，拒绝覆盖与路径穿越
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — |  |
| guest_username | string | 是 | 选项 | （必填） | — |  |
| credential_ref | string | 是 | 选项 | （必填） | — |  |
| os_family | string | 是 | 选项 | （必填） | 枚举 linux/windows |  |
| guest_path | string | 是 | 选项 | （必填） | — |  |
| file | string | 是 | 选项 | （必填） | — | 本地目标文件，已存在则拒绝 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm guest-download --vm-id vm-101 --guest-username root --credential-ref env:GUEST_PASS --os-family linux
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_guest_transfer.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm guest-exec`  ·  远端写（确认执行）
- **operation_id**：`vm.guest_exec`
- **handler**：`application.commands.guest:guest_exec`　|　**provider_kind**：`guest`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.GuestOperations.Execute`, `VirtualMachine.GuestOperations.Query`
- **说明**：预览显式 Python 包装器；输出丢弃，完成由独立运行标识核对
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — |  |
| guest_username | string | 是 | 选项 | （必填） | — |  |
| credential_ref | string | 是 | 选项 | （必填） | — |  |
| os_family | string | 是 | 选项 | （必填） | 枚举 linux/windows |  |
| python_path | string | 是 | 选项 | （必填） | — |  |
| program | string | 是 | 选项 | （必填） | — |  |
| argv | array | 否 | 选项 | `[]` | — |  |
| working_directory | string | 是 | 选项 | （必填） | — |  |
| run_parent | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm guest-exec --vm-id vm-101 --guest-username root --credential-ref env:GUEST_PASS --os-family linux
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_guest_customize_flow.py`, `test_guest_processes.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm guest-exec-output`  ·  远端写（确认执行）
- **operation_id**：`vm.guest_exec_output`
- **handler**：`application.commands.guest:guest_exec_output`　|　**provider_kind**：`guest`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.GuestOperations.Execute`, `VirtualMachine.GuestOperations.Query`
- **说明**：执行并在 Guest 侧有界捕获 stdout/stderr（各 ≤64KiB）；完成绑定本次 run-id，不凭 PID 判定
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — |  |
| guest_username | string | 是 | 选项 | （必填） | — |  |
| credential_ref | string | 是 | 选项 | （必填） | — |  |
| os_family | string | 是 | 选项 | （必填） | 枚举 linux/windows |  |
| python_path | string | 是 | 选项 | （必填） | — |  |
| program | string | 是 | 选项 | （必填） | — |  |
| argv | array | 否 | 选项 | `[]` | — |  |
| working_directory | string | 是 | 选项 | （必填） | — |  |
| run_parent | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm guest-exec-output --vm-id vm-101 --guest-username root --credential-ref env:GUEST_PASS --os-family linux
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_foundation.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_guest_transfer.py`, `test_provider_routing.py`, `test_secrets.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm guest-output`  ·  远端只读
- **operation_id**：`vm.guest_output`
- **handler**：`application.commands.guest:guest_output`　|　**provider_kind**：`guest`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.GuestOperations.Query`
- **说明**：凭可信 run-id 只读已有运行的有界输出，不重新执行；缺失/损坏/身份不符返回不确定
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| run_id | string | 是 | 位置参数 | （必填） | — |  |
| wait | boolean | 否 | 选项 | `false` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm guest-output <run_id>
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_guest_transfer.py`, `test_guest_processes.py`
  - 备注：凭 run-id 经 store.guest_run 反查只读；输出解码/标记解析由纯逻辑覆盖，无独立 CLI 字面用例
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm guest-process-status`  ·  远端只读
- **operation_id**：`vm.guest_process_status`
- **handler**：`application.commands.guest:guest_process_status`　|　**provider_kind**：`guest`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.GuestOperations.Query`
- **说明**：只核对已有 Guest 操作的运行标识与原子结果；不重发
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| operation_id | string | 是 | 位置参数 | （必填） | — |  |
| wait | boolean | 否 | 选项 | `false` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm guest-process-status <op-id>
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_guest_processes.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm guest-upload`  ·  远端写（确认执行）
- **operation_id**：`vm.guest_upload`
- **handler**：`application.commands.guest:guest_upload`　|　**provider_kind**：`guest`　|　**风险**：change　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.GuestOperations.Execute`
- **说明**：上传本地文件（≤4MiB）到 Guest 精确路径；默认拒绝覆盖，显式 overwrite 才覆盖
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — |  |
| guest_username | string | 是 | 选项 | （必填） | — |  |
| credential_ref | string | 是 | 选项 | （必填） | — |  |
| os_family | string | 是 | 选项 | （必填） | 枚举 linux/windows |  |
| file | string | 是 | 选项 | （必填） | — | 本地源文件 |
| guest_path | string | 是 | 选项 | （必填） | — |  |
| overwrite | boolean | 否 | 选项 | `false` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm guest-upload --vm-id vm-101 --guest-username root --credential-ref env:GUEST_PASS --os-family linux
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_guest_transfer.py`, `test_ovf_lease.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm inspect`  ·  远端只读
- **operation_id**：`vm.inspect`
- **handler**：`application.commands.queries:vm_inspect`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：精确查看 VM
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| id | string | 否 | 选项 | 无默认 | — |  |
| name | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm inspect --id <id> --name demo-vm
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_contracts.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm list`  ·  远端只读
- **operation_id**：`vm.list`
- **handler**：`application.commands.queries:vm_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：查看 VM 清单
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm list --limit 1
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_cache.py`, `test_foundation.py`, `test_history_presets_policy.py`, `test_membership.py`, `test_provider.py`, `test_read_models.py`, `test_real_type_contracts.py`, `test_vm_creation.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm migrate`  ·  远端写（确认执行）
- **operation_id**：`vm.migrate`
- **handler**：`application.commands.changes:vm_migrate`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Resource.ColdMigrate`
- **说明**：省略 datastore_id 仅允许明确无磁盘且无 NVDIMM 的计算迁移；带磁盘时缺 PBM 策略证据而拒绝；指定存储也拒绝
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| pool_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 否 | 选项 | 无默认 | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm migrate --vm-id vm-101 --pool-id resgroup-9 --host-id host-21 --datastore-id datastore-30
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_linked_clone_strict.py`, `test_placement.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm power-off`  ·  远端写（确认执行）
- **operation_id**：`vm.power_off`
- **handler**：`application.commands.changes:vm_power_off`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Interact.PowerOff`
- **说明**：强制关机，可能丢失未保存数据
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm power-off --vm-id vm-101
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_provider_routing.py`, `test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm power-on`  ·  远端写（确认执行）
- **operation_id**：`vm.power_on`
- **handler**：`application.commands.changes:vm_power_on`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Interact.PowerOn`
- **说明**：预览开机，不隐式创建 VM
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm power-on --vm-id vm-101
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_execution.py`, `test_foundation.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_plans.py`, `test_provider_routing.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm reconfigure`  ·  远端写（确认执行）
- **operation_id**：`vm.reconfigure`
- **handler**：`application.commands.changes:vm_reconfigure`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Config.CPUCount`, `VirtualMachine.Config.Memory`, `VirtualMachine.Config.DiskExtend`, `VirtualMachine.Config.AddNewDisk`
- **说明**：关机状态下修改 CPU/内存及显式磁盘列表；容量单位 GiB；磁盘不可补偿
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| cpu | integer | 否 | 选项 | 无默认 | ≥1 |  |
| memory_gb | integer | 否 | 选项 | 无默认 | ≥1 |  |
| disks | array | 否 | 选项 | 无默认 | 数组项 2 种唯一形态 | 显式 add/expand；capacity_gb 单位 GiB；add 使用负 device_key 和现有 SCSI 槽位 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm reconfigure --vm-id vm-101 --cpu 1 --memory-gb 1 --disks '[]'
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_plans.py`, `test_provider_routing.py`, `test_vm_devices.py`, `test_vm_provider.py`, `test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm rename`  ·  远端写（确认执行）
- **operation_id**：`vm.rename`
- **handler**：`application.commands.changes:vm_rename`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Config.Rename`
- **说明**：只修改 VM 名称
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| new_name | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm rename --vm-id vm-101 --new-name demo-vm-renamed
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`, `test_plans.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm reset`  ·  远端写（确认执行）
- **operation_id**：`vm.reset`
- **handler**：`application.commands.changes:vm_reset`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Interact.Reset`
- **说明**：硬重置 VM
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm reset --vm-id vm-101
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：③共享执行轨（经已测试的 Engine+Mutations 轨，该动词专属 SDK 分支无离线用例）
  - 备注：经 Engine+Mutations 共享写轨；专属 ResetVM_Task 分支无离线用例
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm shutdown`  ·  远端写（确认执行）
- **operation_id**：`vm.shutdown`
- **handler**：`application.commands.changes:vm_shutdown`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Interact.PowerOff`
- **说明**：优雅关机，不回退强制关机
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm shutdown --vm-id vm-101
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm snapshot-create`  ·  远端写（确认执行）
- **operation_id**：`vm.snapshot_create`
- **handler**：`application.commands.changes:vm_snapshot_create`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.State.CreateSnapshot`
- **说明**：创建快照，不默认为内存快照
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| snapshot_name | string | 是 | 选项 | （必填） | — |  |
| description | string | 否 | 选项 | 无默认 | — |  |
| memory | boolean | 否 | 选项 | `false` | — |  |
| quiesce | boolean | 否 | 选项 | `false` | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm snapshot-create --vm-id vm-101 --snapshot-name snap-before --description <description> --memory
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm snapshot-delete`  ·  远端写（确认执行）
- **operation_id**：`vm.snapshot_delete`
- **handler**：`application.commands.changes:vm_snapshot_delete`　|　**provider_kind**：`vm`　|　**风险**：destructive　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.State.RemoveSnapshot`
- **说明**：严格保护：无法排除外部链接磁盘依赖时拒绝清理；当前不能执行
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| snapshot_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm snapshot-delete --vm-id vm-101 --snapshot-id snapshot-2
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_linked_clone_strict.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm snapshot-list`  ·  远端只读
- **operation_id**：`vm.snapshot_list`
- **handler**：`application.commands.queries:vm_snapshot_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：读取带精确快照 ID 的树
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm snapshot-list --vm-id vm-101 --limit 1
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_read_models.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm snapshot-revert`  ·  远端写（确认执行）
- **operation_id**：`vm.snapshot_revert`
- **handler**：`application.commands.changes:vm_snapshot_revert`　|　**provider_kind**：`vm`　|　**风险**：destructive　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.State.RevertToSnapshot`
- **说明**：严格保护：无法排除外部链接磁盘依赖时拒绝恢复；当前不能执行
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| snapshot_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm snapshot-revert --vm-id vm-101 --snapshot-id snapshot-2
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_linked_clone_strict.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm suspend`  ·  远端写（确认执行）
- **operation_id**：`vm.suspend`
- **handler**：`application.commands.changes:vm_suspend`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Interact.Suspend`
- **说明**：挂起 VM
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm suspend --vm-id vm-101
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：③共享执行轨（经已测试的 Engine+Mutations 轨，该动词专属 SDK 分支无离线用例）
  - 备注：经 Engine+Mutations 共享写轨；专属 SuspendVM_Task 分支无离线用例
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm tools-status`  ·  远端只读
- **operation_id**：`vm.tools_status`
- **handler**：`application.commands.queries:vm_tools_status`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：读取 Tools 状态，缺失字段不编造
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm tools-status --vm-id vm-101
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_read_models.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `vm wait-tools`  ·  远端只读
- **operation_id**：`vm.wait_tools`
- **handler**：`application.commands.queries:vm_wait_tools`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：限时等待 Tools 就绪，不修改 VM
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab vm wait-tools --vm-id vm-101
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_execution.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_plans.py`, `test_read_models.py`, `test_search_cli.py`, `test_search_recovery.py`, `test_secrets.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `template`

### `template convert`  ·  远端写（确认执行）
- **operation_id**：`template.convert`
- **handler**：`application.commands.changes:template_convert`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Provisioning.MarkAsVM`, `Resource.AssignVMToPool`
- **说明**：将精确模板转换为 VM，不改名不开机
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| pool_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab template convert --vm-id vm-101 --pool-id resgroup-9 --host-id host-21
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_templates_linked.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `template inspect`  ·  远端只读
- **operation_id**：`template.inspect`
- **handler**：`application.commands.queries:template_inspect`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：精确查询模板，排除普通 VM
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| id | string | 否 | 选项 | 无默认 | — |  |
| name | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab template inspect --id <id> --name demo-vm
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_linked_clone_strict.py`, `test_placement.py`, `test_read_models.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `template list`  ·  远端只读
- **operation_id**：`template.list`
- **handler**：`application.commands.queries:template_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：仅查询模板
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab template list --limit 1
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_linked_clone_strict.py`, `test_placement.py`, `test_read_models.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `deploy`

### `deploy clone-template`  ·  远端写（确认执行）
- **operation_id**：`deploy.clone_template`
- **handler**：`application.commands.changes:deploy_clone_template`　|　**provider_kind**：`template_clone`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Provisioning.DeployTemplate`, `VirtualMachine.Inventory.CreateFromExisting`, `Resource.AssignVMToPool`, `Datastore.AllocateSpace`, `Network.Assign`, `VirtualMachine.Interact.PowerOn`, `VirtualMachine.Provisioning.Customize`
- **说明**：对齐 vcenter-ops 克隆模版标准流程：从模板一次性克隆；可选改网/CPU/内存/磁盘扩容/静态 IP（给 IP 即开机 Linux 定制，不给则关机）；host_id 省略走集群 DRS
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确模板对象 ID，如 vm-123 |
| name | string | 是 | 选项 | （必填） | — | 新 VM 名称，1–80 字符 |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| pool_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 否 | 选项 | 无默认 | — | 省略时由集群 DRS 调度 |
| network_id | string | 否 | 选项 | 无默认 | — | 省略则保留模板网卡；标准网络 network-N 或分布式端口组 dvportgroup-N |
| cpu | integer | 否 | 选项 | 无默认 | ≥1 | 克隆时改配 CPU 核数；省略保留模板 |
| memory_gb | integer | 否 | 选项 | 无默认 | ≥1 | 克隆时改配内存 GiB；省略保留模板 |
| disk_gb | integer | 否 | 选项 | 无默认 | ≥1 | 首盘目标容量 GiB，仅支持大于模板当前值的扩容 |
| ip_address | string | 否 | 选项 | 无默认 | — | 给定静态 IPv4 即开机并下发 Linux 定制；省略则克隆为关机 VM |
| subnet_mask | string | 否 | 选项 | `"255.255.255.0"` | — | 静态 IP 子网掩码，默认 255.255.255.0 |
| gateway | string | 否 | 选项 | 无默认 | — | 静态 IP 默认网关；省略则不设网关 |
| guest_domain | string | 否 | 选项 | `"local"` | — | Linux 定制域，默认 local |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy clone-template --vm-id vm-101 --name demo-vm --folder-id group-v4 --pool-id resgroup-9
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_template_clone.py`, `test_template_clone_flow.py`
  - 备注：Provider preflight/submit/observe/verify 全链路 + Engine preview/apply/去重/取消/补偿边界被直接断言；命令仅为薄 preview 包装层，未逐字走 CLI（路径字面量仅作 preflight 实参）
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `deploy iso`  ·  远端写（确认执行）
- **operation_id**：`deploy.iso`
- **handler**：`application.commands.changes:deploy_iso`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Config.EditDevice`, `VirtualMachine.Interact.SetCDMedia`, `VirtualMachine.Interact.DeviceConnection`, `Datastore.Browse`
- **说明**：编辑已有光驱装载 ISO；先 browse/scan + search-status 完成搜索，search_id 创建时间须在300秒内
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| cdrom_key | integer | 是 | 选项 | （必填） | ≥0 |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| path | string | 是 | 选项 | （必填） | — |  |
| search_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy iso --vm-id vm-101 --cdrom-key 1 --datastore-id datastore-30 --path /iso/setup.iso
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_vm_media.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `deploy linked-clone`  ·  远端写（确认执行）
- **operation_id**：`deploy.linked_clone`
- **handler**：`application.commands.linked:deploy_linked_clone`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Provisioning.Clone`, `VirtualMachine.Inventory.CreateFromExisting`, `Resource.AssignVMToPool`, `Datastore.AllocateSpace`, `Datastore.Browse`, `Network.Assign`
- **说明**：从精确父 UUID/快照创建关机链接克隆；依赖长期保留，不能排除依赖时拒绝父磁盘清理；许可最终由服务端校验
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — |  |
| parent_uuid | string | 是 | 选项 | （必填） | — |  |
| snapshot_id | string | 是 | 选项 | （必填） | — |  |
| name | string | 是 | 选项 | （必填） | — |  |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| pool_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy linked-clone --vm-id vm-101 --parent-uuid <parent_uuid> --snapshot-id snapshot-2 --name demo-vm
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_linked_clone_strict.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `deploy mark-template`  ·  远端写（确认执行）
- **operation_id**：`deploy.mark_template`
- **handler**：`application.commands.changes:deploy_mark_template`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Provisioning.MarkAsTemplate`
- **说明**：只转换为模板，不重命名
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy mark-template --vm-id vm-101
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：③共享执行轨（经已测试的 Engine+Mutations 轨，该动词专属 SDK 分支无离线用例）
  - 备注：经 Engine+Mutations 共享写轨；专属 MarkAsTemplate 分支无离线用例
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `deploy ova`  ·  远端写（确认执行）
- **operation_id**：`deploy.ova`
- **handler**：`application.commands.ovf:deploy_ova`　|　**provider_kind**：`ovf`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VApp.Import`, `Datastore.AllocateSpace`, `Datastore.Browse`, `Network.Assign`, `Resource.AssignVMToPool`
- **说明**：从本地单文件 OVA 导入关机 VM/ vApp：先安全解包（拒绝路径穿越）与描述符/网络/磁盘校验，再 OvfManager + NFC 上传；默认不开机、不隐式定制；中断须核对不重发
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| source | string | 是 | 位置参数 | （必填） | — | 本地 .ova 文件路径 |
| work_dir | string | 是 | 选项 | （必填） | — | 解包工作目录；在其中创建 unpacked/ |
| name | string | 是 | 选项 | （必填） | — |  |
| resource_pool_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| network_mapping | object | 是 | 选项 | （必填） | — | 描述符网络名到精确网络 ID 的映射，例如 {"VM Network":"network-12"}；目标须为 network-N 或 dvportgroup-N |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy ova <source> --work-dir <work_dir> --name demo-vm --resource-pool-id <resource_pool_id>
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `deploy ovf`  ·  远端写（确认执行）
- **operation_id**：`deploy.ovf`
- **handler**：`application.commands.ovf:deploy_ovf`　|　**provider_kind**：`ovf`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VApp.Import`, `Datastore.AllocateSpace`, `Datastore.Browse`, `Network.Assign`, `Resource.AssignVMToPool`
- **说明**：从本地 OVF 目录（descriptor.ovf + 引用磁盘）导入关机 VM/ vApp：校验映射后 OvfManager + NFC 上传；默认不开机、不隐式定制；中断须核对不重发
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| source | string | 是 | 位置参数 | （必填） | — | 含 descriptor.ovf 的本地目录 |
| work_dir | string | 是 | 选项 | （必填） | — |  |
| name | string | 是 | 选项 | （必填） | — |  |
| resource_pool_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| network_mapping | object | 是 | 选项 | （必填） | — | 描述符网络名到精确网络 ID 的映射，例如 {"VM Network":"network-12"}；目标须为 network-N 或 dvportgroup-N |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy ovf <source> --work-dir <work_dir> --name demo-vm --resource-pool-id <resource_pool_id>
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_foundation.py`, `test_ovf_deploy.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `deploy template`  ·  远端写（确认执行）
- **operation_id**：`deploy.template`
- **handler**：`application.commands.changes:deploy_template`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Provisioning.DeployTemplate`
- **说明**：从模板部署关机 VM
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| pool_id | string | 是 | 选项 | （必填） | — |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| name | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy template --vm-id vm-101 --pool-id resgroup-9 --datastore-id datastore-30 --host-id host-21
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_placement.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `deploy unmount-iso`  ·  远端写（确认执行）
- **operation_id**：`deploy.unmount_iso`
- **handler**：`application.commands.changes:deploy_unmount_iso`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`VirtualMachine.Config.EditDevice`, `VirtualMachine.Interact.SetCDMedia`, `VirtualMachine.Interact.DeviceConnection`
- **说明**：断开并清除已有光驱介质，不删除 ISO
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_id | string | 是 | 选项 | （必填） | — | 精确 VM 对象 ID，如 vm-123 |
| cdrom_key | integer | 是 | 选项 | （必填） | ≥0 |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab deploy unmount-iso --vm-id vm-101 --cdrom-key 1
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_vm_media.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `host`

### `host info`  ·  远端只读
- **operation_id**：`host.info`
- **handler**：`application.commands.queries:host_info`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：精确查看主机
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| id | string | 否 | 选项 | 无默认 | — |  |
| name | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab host info --id <id> --name demo-vm
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_cache.py`, `test_foundation.py`, `test_history_presets_policy.py`, `test_membership.py`, `test_provider.py`, `test_read_models.py`, `test_real_type_contracts.py`, `test_vm_creation.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `host maintenance-enter`  ·  远端写（确认执行）
- **operation_id**：`host.maintenance_enter`
- **handler**：`application.commands.hosts:host_maintenance_enter`　|　**provider_kind**：`host`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Host.Config.Maintenance`
- **说明**：显式预览 VM/DRS 影响后让精确主机进入维护模式
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| host_id | string | 是 | 选项 | （必填） | — | 精确 host-N 对象 ID，如 host-123 |
| task_timeout | integer | 否 | 选项 | `300` | ≥1；≤86400 |  |
| evacuate_powered_off_vms | boolean | 否 | 选项 | `false` | — |  |
| allow_drs_migration | boolean | 否 | 选项 | `false` | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab host maintenance-enter --host-id host-21 --task-timeout 1 --evacuate-powered-off-vms --allow-drs-migration
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_host_maintenance.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `host maintenance-exit`  ·  远端写（确认执行）
- **operation_id**：`host.maintenance_exit`
- **handler**：`application.commands.hosts:host_maintenance_exit`　|　**provider_kind**：`host`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Host.Config.Maintenance`
- **说明**：让精确主机退出维护模式，不创建额外撤离操作
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| host_id | string | 是 | 选项 | （必填） | — | 精确 host-N 对象 ID，如 host-123 |
| task_timeout | integer | 否 | 选项 | `300` | ≥1；≤86400 |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab host maintenance-exit --host-id host-21 --task-timeout 1
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_host_maintenance.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `cluster`

### `cluster configure`  ·  远端写（确认执行）
- **operation_id**：`cluster.configure`
- **handler**：`application.commands.clusters:cluster_configure`　|　**provider_kind**：`cluster`　|　**风险**：change　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Host.Inventory.EditCluster`
- **说明**：只增量修改明确选择的 HA/DRS 字段
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| cluster_id | string | 是 | 选项 | （必填） | — |  |
| ha_enabled | boolean | 否 | 选项 | 无默认 | — |  |
| drs_enabled | boolean | 否 | 选项 | 无默认 | — |  |
| drs_automation | string | 否 | 选项 | 无默认 | 枚举 manual/partiallyAutomated/fullyAutomated |  |
| drs_vmotion_rate | integer | 否 | 选项 | 无默认 | ≥1；≤5 |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cluster configure --cluster-id domain-c7 --ha-enabled --drs-enabled --drs-automation manual
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_cluster_lifecycle.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `cluster create`  ·  远端写（确认执行）
- **operation_id**：`cluster.create`
- **handler**：`application.commands.clusters:cluster_create`　|　**provider_kind**：`cluster`　|　**风险**：change　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：`Host.Inventory.CreateCluster`
- **说明**：在精确 host folder 创建集群
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| folder_id | string | 是 | 选项 | （必填） | — |  |
| name | string | 是 | 选项 | （必填） | — |  |
| ha_enabled | boolean | 否 | 选项 | `false` | — |  |
| drs_automation | string | 否 | 选项 | `"manual"` | 枚举 manual/partiallyAutomated/fullyAutomated |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cluster create --folder-id group-v4 --name demo-vm --ha-enabled --drs-automation manual
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_cluster_lifecycle.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `cluster delete`  ·  远端写（确认执行）
- **operation_id**：`cluster.delete`
- **handler**：`application.commands.clusters:cluster_delete`　|　**provider_kind**：`cluster`　|　**风险**：destructive　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Host.Inventory.DeleteCluster`
- **说明**：二次确认后删除精确空集群
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| cluster_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cluster delete --cluster-id domain-c7
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_cluster_lifecycle.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `cluster info`  ·  远端只读
- **operation_id**：`cluster.info`
- **handler**：`application.commands.queries:cluster_info`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：精确查看集群
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| id | string | 否 | 选项 | 无默认 | — |  |
| name | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cluster info --id <id> --name demo-vm
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_cache.py`, `test_foundation.py`, `test_membership.py`, `test_provider.py`, `test_real_type_contracts.py`, `test_vm_creation.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `cluster list`  ·  远端只读
- **operation_id**：`cluster.list`
- **handler**：`application.commands.queries:cluster_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：查看集群
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cluster list --limit 1
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_cache.py`, `test_foundation.py`, `test_membership.py`, `test_provider.py`, `test_real_type_contracts.py`, `test_vm_creation.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `cluster remove-host`  ·  远端写（确认执行）
- **operation_id**：`cluster.remove_host`
- **handler**：`application.commands.clusters:cluster_remove_host`　|　**provider_kind**：`membership`　|　**风险**：destructive　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Host.Inventory.EditCluster`, `Host.Inventory.MoveHost`, `Host.Inventory.AddStandaloneHost`
- **说明**：保留在 vCenter，转为独立主机；需要二次确认
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| cluster_id | string | 是 | 选项 | （必填） | — |  |
| host_id | string | 是 | 选项 | （必填） | — |  |
| folder_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cluster remove-host --cluster-id domain-c7 --host-id host-21 --folder-id group-v4
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_enrollment_unavailable.py`, `test_membership.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `datastore`

### `datastore browse`  ·  远端只读
- **operation_id**：`datastore.browse`
- **handler**：`application.commands.datastores:browse`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Datastore.Browse`
- **说明**：浏览目录；显式 recursive 才包含子目录
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| path | string | 否 | 选项 | `""` | — |  |
| recursive | boolean | 否 | 选项 | `false` | — | 显式包含子目录；limit 仅限制输出，不限制服务端搜索工作量 |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab datastore browse --limit 1 --datastore-id datastore-30 --path /iso/setup.iso
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_datastore_browser.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `datastore inspect`  ·  远端只读
- **operation_id**：`datastore.inspect`
- **handler**：`application.commands.queries:datastore_inspect`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：精确查看数据存储
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| id | string | 否 | 选项 | 无默认 | — |  |
| name | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab datastore inspect --id <id> --name demo-vm
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_cache.py`, `test_datastore_browser.py`, `test_foundation.py`, `test_membership.py`, `test_provider.py`, `test_real_type_contracts.py`, `test_search_cli.py`, `test_vm_creation.py`, `test_vm_media.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `datastore list`  ·  远端只读
- **operation_id**：`datastore.list`
- **handler**：`application.commands.queries:datastore_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：查看数据存储
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab datastore list --limit 1
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_cache.py`, `test_datastore_browser.py`, `test_foundation.py`, `test_membership.py`, `test_provider.py`, `test_real_type_contracts.py`, `test_search_cli.py`, `test_vm_creation.py`, `test_vm_media.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `datastore scan`  ·  远端只读
- **operation_id**：`datastore.scan`
- **handler**：`application.commands.datastores:scan`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：是　|　**MCP 暴露**：是
- **所需特权**：`Datastore.Browse`
- **说明**：发现 ISO/OVA/OVF，持久化搜索任务，不部署
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
| datastore_id | string | 是 | 选项 | （必填） | — |  |
| path | string | 否 | 选项 | `""` | — |  |
| recursive | boolean | 否 | 选项 | `false` | — | 显式包含子目录；limit 仅限制输出，不限制服务端搜索工作量 |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab datastore scan --limit 1 --datastore-id datastore-30 --path /iso/setup.iso
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_datastore_browser.py`, `test_search_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `datastore search-inspect`  ·  本地只读
- **operation_id**：`datastore.search_inspect`
- **handler**：`application.commands.datastores:search_inspect`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：查看本地搜索记录及已保存结果
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| search_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab datastore search-inspect <search_id>
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_search_cli.py`

### `datastore search-list`  ·  本地只读
- **operation_id**：`datastore.search_list`
- **handler**：`application.commands.datastores:search_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：列出当前 Profile 的搜索记录
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab datastore search-list --limit 1
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_search_cli.py`

### `datastore search-status`  ·  远端只读
- **operation_id**：`datastore.search_status`
- **handler**：`application.commands.datastores:search_status`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：核对原搜索任务，不重新搜索
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| search_id | string | 是 | 位置参数 | （必填） | — |  |
| wait | boolean | 否 | 选项 | `false` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab datastore search-status <search_id>
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_search_cli.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `alarm`

### `alarm acknowledge`  ·  远端写（确认执行）
- **operation_id**：`alarm.acknowledge`
- **handler**：`application.commands.changes:alarm_acknowledge`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：确认精确实体上的告警，不代表故障恢复
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| entity_id | string | 是 | 选项 | （必填） | — |  |
| alarm_id | string | 是 | 选项 | （必填） | — |  |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab alarm acknowledge --entity-id vm-101 --alarm-id alarm-12
```
- **预期结果**：远端写：默认先做只读预检并持久化固定计划，返回 `awaiting_confirmation`（data 含 id/digest/confirmation/confirmation_expires）；`plan apply <id> --confirm <digest>` 后提交，成功 status=succeeded；写后超时/响应丢失返回 reconciliation_required，不自动重发。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_alarms.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `alarm list`  ·  远端只读
- **operation_id**：`alarm.list`
- **handler**：`application.commands.queries:alarm_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：读取指定对象及后代的可见触发告警，不确认或重置
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
| entity_id | string | 否 | 选项 | 无默认 | — | 省略时查询根目录及后代；提供精确对象 ID 限定范围 |
| status | string | 否 | 选项 | 无默认 | 枚举 red/yellow/green/gray |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab alarm list --limit 1 --entity-id vm-101 --status red
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `alarm reset`  ·  远端写（确认执行）
- **operation_id**：`alarm.reset`
- **handler**：`application.commands.changes:alarm_reset`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：`Alarm.SetStatus`
- **说明**：按受管对象类型+状态批量清除触发告警（6.7+，只能 vm/host，不能精确定位单个告警/实体）；预览绑定精确告警集合
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| entity_type | string | 是 | 选项 | （必填） | 枚举 vm/host | ClearTriggeredAlarms 的类型过滤仅有 VM/Host；不支持单个实体、告警 ID 或集群/数据存储 |
| statuses | array | 否 | 选项 | 无默认 | — | 默认 red+yellow；只允许 red/yellow，去重 |
| dry_run | boolean | 否 | 选项 | `false` | — |  |
| request_id | string | 否 | 选项 | 无默认 | — |  |
| wait | boolean | 否 | 选项 | `true` | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab alarm reset --entity-type vm --statuses '["red","yellow"]'
```
- **预期结果**：先预览返回 awaiting_confirmation 并绑定精确告警 key 集合；apply 后 data={reset,command,requested_count}；6.5 返回 capability_unsupported；提交前范围扩大返回 plan_stale。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_alarm_reset.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `cache`

### `cache invalidate`  ·  本地写入
- **operation_id**：`cache.invalidate`
- **handler**：`application.commands.cache:invalidate`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：仅删除指定 Profile 和资产类型的所有已记录服务端缓存
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| kind | string | 是 | 选项 | （必填） | 枚举 vm/host/cluster/datastore |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cache invalidate --kind vm
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_cache.py`

### `cache refresh`  ·  远端只读
- **operation_id**：`cache.refresh`
- **handler**：`application.commands.cache:refresh`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：显式从远端只读刷新资产缓存；最多 1000 项且限制快照字节数（TTL 300 秒）
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| kind | string | 是 | 选项 | （必填） | 枚举 vm/host/cluster/datastore |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cache refresh --kind vm
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_cache.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `cache status`  ·  本地只读
- **operation_id**：`cache.status`
- **handler**：`application.commands.cache:status`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：离线查看指定 Profile 的资产缓存年龄、来源及服务端身份（TTL 300 秒）
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| kind | string | 是 | 选项 | （必填） | 枚举 vm/host/cluster/datastore |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab cache status --kind vm
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_audit.py`, `test_cache.py`, `test_cluster_lifecycle.py`, `test_execution.py`, `test_foundation.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_plans.py`, `test_provider_routing.py`, `test_search_cli.py`, `test_search_recovery.py`, `test_secrets.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_write_cli.py`


---

## 领域 `task`

### `task cancel`  ·  编排/恢复
- **operation_id**：`task.cancel`
- **handler**：`application.commands.plans:task_cancel`　|　**provider_kind**：`vm`　|　**风险**：change　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：请求取消原任务，不将请求等同已取消
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| operation_id | string | 是 | 位置参数 | （必填） | — |  |
| confirm | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab task cancel <op-id>
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_template_clone_flow.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `task inspect`  ·  本地只读
- **operation_id**：`task.inspect`
- **handler**：`application.commands.plans:task_inspect`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：查看持久化操作与任务身份
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| operation_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab task inspect <op-id>
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_write_cli.py`

### `task list`  ·  本地只读
- **operation_id**：`task.list`
- **handler**：`application.commands.plans:task_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：查询本地操作记录
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab task list --limit 1
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_alarms.py`, `test_cluster_lifecycle.py`, `test_datastore_browser.py`, `test_enrollment_unavailable.py`, `test_execution.py`, `test_guest_customize_flow.py`, `test_guest_processes.py`, `test_history_presets_policy.py`, `test_host_maintenance.py`, `test_linked_clone_strict.py`, `test_membership.py`, `test_operation_state.py`, `test_plans.py`, `test_provider_routing.py`, `test_real_type_contracts.py`, `test_search_recovery.py`, `test_template_clone.py`, `test_template_clone_flow.py`, `test_templates_linked.py`, `test_vm_creation.py`, `test_vm_devices.py`, `test_vm_media.py`, `test_vm_provider.py`, `test_write_cli.py`

### `task reconcile`  ·  远端只读
- **operation_id**：`task.reconcile`
- **handler**：`application.commands.plans:task_reconcile`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：只核对已提交任务
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| operation_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab task reconcile <op-id>
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_linked_clone_strict.py`, `test_execution.py`
  - 备注：handler task_reconcile/Engine 核对路径被直接断言，不重复提交
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `task wait`  ·  远端只读
- **operation_id**：`task.wait`
- **handler**：`application.commands.plans:task_wait`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：限时等待已提交任务，不重发
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| operation_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab task wait <op-id>
```
- **预期结果**：只读：status=succeeded，data 为该读模型对象；查询被截断显式标记 truncated，不把部分结果当完整清单；不修改远端。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_guest_processes.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `batch`

### `batch power-off`  ·  编排/恢复
- **operation_id**：`batch.power_off`
- **handler**：`application.commands.plans:batch_power_off`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：只构建固定对象计划，不提交远端变更
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_ids | array | 是 | 选项 | （必填） | — | JSON 数组，例如 ["vm-1","vm-2"] |
| request_id | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab batch power-off --vm-ids '["vm-1","vm-2"]'
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_foundation.py`, `test_linked_clone_strict.py`, `test_plans.py`, `test_provider_routing.py`, `test_templates_linked.py`, `test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `batch power-on`  ·  编排/恢复
- **operation_id**：`batch.power_on`
- **handler**：`application.commands.plans:batch_power_on`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：只构建固定对象计划，不提交远端变更
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_ids | array | 是 | 选项 | （必填） | — | JSON 数组，例如 ["vm-1","vm-2"] |
| request_id | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab batch power-on --vm-ids '["vm-1","vm-2"]'
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_provider_routing.py`
  - 备注：plans.batch_power_on 被直接调用，断言只构建固定对象计划不提交
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `batch reset`  ·  编排/恢复
- **operation_id**：`batch.reset`
- **handler**：`application.commands.plans:batch_reset`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：只构建固定对象计划，不提交远端变更
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_ids | array | 是 | 选项 | （必填） | — | JSON 数组，例如 ["vm-1","vm-2"] |
| request_id | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab batch reset --vm-ids '["vm-1","vm-2"]'
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_foundation.py`, `test_linked_clone_strict.py`, `test_plans.py`, `test_provider_routing.py`, `test_templates_linked.py`, `test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。

### `batch shutdown`  ·  编排/恢复
- **operation_id**：`batch.shutdown`
- **handler**：`application.commands.plans:batch_shutdown`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：是
- **所需特权**：—
- **说明**：只构建固定对象计划，不提交远端变更
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| vm_ids | array | 是 | 选项 | （必填） | — | JSON 数组，例如 ["vm-1","vm-2"] |
| request_id | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab batch shutdown --vm-ids '["vm-1","vm-2"]'
```
- **预期结果**：编排/恢复：只核对或驱动既有计划/任务，不重复提交远端写；返回计划或操作状态（含 ready_to_resume/reconciliation_required）。
- **离线测试状态**：②逻辑级离线测试（底层纯函数/Provider 被断言，命令薄包装层未逐字走 CLI）
  - 覆盖文件：`test_alarm_reset.py`, `test_foundation.py`, `test_linked_clone_strict.py`, `test_plans.py`, `test_provider_routing.py`, `test_templates_linked.py`, `test_vm_provider.py`
- **vSphere 实机**：6.5/6.7/7.0/8.0 均 `not_lab_verified`，待真机验收。


---

## 领域 `secret`

### `secret delete`  ·  本地写入
- **operation_id**：`secret.delete`
- **handler**：`application.commands.secrets:delete_secret`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：删除全局精确名称的秘密
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | 全局精确名称：[A-Za-z0-9_-]{1,64} |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops secret delete demo-vm
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_secrets.py`

### `secret list`  ·  本地只读
- **operation_id**：`secret.list`
- **handler**：`application.commands.secrets:list_secrets`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：列出全局秘密的名称、修订号和 UTC 时间；拒绝 Profile 过滤
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| _（无参数）_ | | | | | | |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops secret list
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_secrets.py`

### `secret rotate`  ·  本地写入
- **operation_id**：`secret.rotate`
- **handler**：`application.commands.secrets:rotate_secret`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：替换精确秘密值并递增修订号；不是主密钥轮换，最多 4096 UTF-8 字节
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | 全局精确名称：[A-Za-z0-9_-]{1,64} |
| stdin | boolean | 否 | 选项 | `false` | — | 显式从 stdin 读取非空 UTF-8 秘密，最多 4096 字节；仅移除一个结尾换行，否则使用隐藏终端输入 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops secret rotate demo-vm --stdin
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_secrets.py`

### `secret set`  ·  本地写入
- **operation_id**：`secret.set`
- **handler**：`application.commands.secrets:set_secret`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：创建全局秘密，不覆盖已有项；值最多 4096 UTF-8 字节
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | 全局精确名称：[A-Za-z0-9_-]{1,64} |
| stdin | boolean | 否 | 选项 | `false` | — | 显式从 stdin 读取非空 UTF-8 秘密，最多 4096 字节；仅移除一个结尾换行，否则使用隐藏终端输入 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops secret set demo-vm --stdin
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_secrets.py`


---

## 领域 `history`

### `history list`  ·  本地只读
- **operation_id**：`history.list`
- **handler**：`application.commands.history_presets:history_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：分页查看本地计划历史；无 --profile 时明确查询全局
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
| after_id | integer | 否 | 选项 | `0` | ≥0 |  |
| snapshot_max_id | integer | 否 | 选项 | 无默认 | ≥0 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab history list --limit 1 --after-id 0 --snapshot-max-id 1
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`

### `history show`  ·  本地只读
- **operation_id**：`history.show`
- **handler**：`application.commands.history_presets:history_show`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：精确查看计划与操作状态；不输出确认值、绑定或回执
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| plan_id | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab history show <plan-id>
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`


---

## 领域 `preset`

### `preset delete`  ·  本地写入
- **operation_id**：`preset.delete`
- **handler**：`application.commands.history_presets:preset_delete`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：删除指定 Profile 内精确名称的预设；须 --profile
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | Profile 内精确预设名 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab preset delete demo-vm
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`

### `preset from-history`  ·  本地写入
- **operation_id**：`preset.from_history`
- **handler**：`application.commands.history_presets:preset_from_history`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：选取同 Profile 历史计划中的一个步骤，新建预设；不复用确认或操作
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | Profile 内精确预设名 |
| plan_id | string | 是 | 选项 | （必填） | — |  |
| position | integer | 是 | 选项 | （必填） | ≥0 |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab preset from-history demo-vm --plan-id <plan-id> --position 1
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`

### `preset from-vm`  ·  本地写入
- **operation_id**：`preset.from_vm`
- **handler**：`application.commands.history_presets:preset_from_vm`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：只读来源 VM，保存目标 VM 的 CPU/整 GiB 内存配置预设；非部署/克隆模板；遗漏磁盘、网卡、控制器、存储及 UUID
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | Profile 内精确预设名 |
| source_vm_id | string | 是 | 选项 | （必填） | — | 精确读取来源 vm-N |
| target_vm_id | string | 是 | 选项 | （必填） | — | 将来配置的目标 vm-N，必须显式提供 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab preset from-vm demo-vm --source-vm-id <source_vm_id> --target-vm-id <target_vm_id>
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`

### `preset list`  ·  本地只读
- **operation_id**：`preset.list`
- **handler**：`application.commands.history_presets:preset_list`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：分页列出指定 Profile 的预设；须 --profile
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| limit | integer | 否 | 选项 | `100` | ≥1；≤1000 |  |
| after_name | string | 否 | 选项 | 无默认 | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab preset list --limit 1 --after-name <after_name>
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`

### `preset save`  ·  本地写入
- **operation_id**：`preset.save`
- **handler**：`application.commands.history_presets:preset_save`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：保存已注册远端原子命令的声明式参数，不预览或部署；须 --profile
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | Profile 内精确预设名 |
| command_path | string | 是 | 选项 | （必填） | — |  |
| params | object | 是 | 选项 | （必填） | — | 当前命令完整 JSON 参数；不含确认、请求 ID、绑定或秘密 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab preset save demo-vm --command-path alarm reset --params '{"key":"value"}'
```
- **预期结果**：本地写入：仅改本机状态（config.yaml/state.db/secrets.json），不联网；失败以错误信封返回。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`

### `preset show`  ·  本地只读
- **operation_id**：`preset.show`
- **handler**：`application.commands.history_presets:preset_show`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：精确查看并重新校验指定 Profile 的预设；须 --profile
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| name | string | 是 | 位置参数 | （必填） | — | Profile 内精确预设名 |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops --profile lab preset show demo-vm
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`


---

## 领域 `policy`

### `policy check`  ·  本地只读
- **operation_id**：`policy.check`
- **handler**：`application.commands.policy:check`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：仅检查静态命令参数；不签发确认、不消耗确认、不提交任务
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| command_path | string | 是 | 位置参数 | （必填） | — |  |
| params | object | 是 | 选项 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops policy check alarm reset --params '{"key":"value"}'
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：①行为级离线测试（CLI/handler 直接断言）
  - 覆盖文件：`test_history_presets_policy.py`, `test_ip_signals.py`, `test_provider_routing.py`

### `policy inspect`  ·  本地只读
- **operation_id**：`policy.inspect`
- **handler**：`application.commands.policy:inspect`　|　**provider_kind**：`vm`　|　**风险**：read_only　|　**异步**：否　|　**MCP 暴露**：否
- **所需特权**：—
- **说明**：查看静态 schema、风险与声明权限；不查询远端权限或授权执行
- **输入参数**：
| 参数 | 类型 | 必填 | 形态 | 默认 | 约束 | 说明 |
|---|---|---|---|---|---|---|
| command_path | string | 是 | 位置参数 | （必填） | — |  |
- **触发方式（CLI，占位值）**：
```text
vcenter-aiops policy inspect alarm reset
```
- **预期结果**：本地只读：status=succeeded，data 为本地计算/查询结果，不联网、不建状态。
- **离线测试状态**：④仅注册契约基线（schema/--help 全量基线，无专属用例）
  - 备注：静态策略视图无专属 CLI/handler 用例，仅被全量 schema/--help 基线覆盖

