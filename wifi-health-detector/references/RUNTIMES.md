# 运行环境与性能

## 自动选择

入口始终是 `run.sh` 或 `run.bat`，顺序为 Python 3.7+ → 系统原生 → Node 16+。`--engine python|native|node` 强制选择，默认 `auto`。选择后发生的采集、网络、权限、导出或通知失败不会触发整套重跑。通过 `WIFI_HEALTH_PYTHON` / `WIFI_HEALTH_NODE` 提供路径即可复用宿主内置环境，不依赖任何特定 Agent 的私有安装路径。不自动下载、安装解释器或第三方包。

Python 扫描限定在显式路径、虚拟环境/Conda、PATH、常见安装位置，Windows 额外查询 Python 安装注册表。逐一验证版本和标准库，单候选限时约 2 秒（异常清理可能略超出），不做全盘扫描、不持久化过期路径。Apple 的 `xcrun` 占位解释器不可用时继续检查后续引擎。

`manifest.json` 的 `requirements` 不再要求 Python；新增 `runtime_fallback` 是说明性元数据。企业 Agent 若有独立依赖校验规则，需要按其规范配置这些可选运行环境，不能把三者解释成全部必需。

## 原生与备用能力

| 路径 | 实现 | 限制 |
|---|---|---|
| Python | 现有采集、评分、报告与可选通知 | 解释器必须实际可执行 |
| macOS 原生 | Shell 入口 + 系统 JXA/Foundation NSTask + 原生命令 | JXA 和本地进程执行能力必须可用；不操作 GUI、不请求辅助功能权限 |
| Windows 原生 | PowerShell 5.1 + .NET + netsh/Get-NetIPConfiguration | 企业脚本策略必须允许；脚本 UTF-8 BOM，报告 UTF-8 |
| Node | 无 npm 依赖，复用 JavaScript 报告和解析规则 | 必须有可调用 Node；不能绕过操作系统权限限制 |

原生与 Node 保留 schema 2.0 和固定五部分/18 行 Markdown；评分使用共享规则测试。Python/Bridge 与备用引擎统一把整数型数值显示成 `0` 而非 `0.0`，不改变数值语义。`system.python_version` 在原生/Node 中不可用，不伪造 Python 版本。

Windows 原生/Node 只在 netsh 提供时报告当前频宽，未提供时不执行 Python ctypes 的 WLAN 补充。macOS 接收 PHY 速率仍保留平台不可用说明。缺失字段不扣分。Windows 信号百分比换算 RSSI 时标记 estimated。

原生/Node 本版本不启动 Python 通知 Bridge，在 stderr 提示该限制；报告及显式导出仍成功。`--no-notify` 可关闭本次提示。Python 引擎保留原有通知授权、配置与去重流程，通知最长等待不包含在采集预算中。

Node 的 Windows IP 采集仍使用系统 PowerShell；如果 PowerShell 完全不可用，该部分保留不可用，不能冒充完整 IP 采集。备用引擎不承诺恢复被系统隐私策略隐藏的 SSID/RSSI。检测必须在目标电脑执行，服务器/容器网络不是用户电脑 Wi-Fi。

## 性能和失败语义

- `--timeout 10`：单项命令/网络测试上限；`--budget 35`：采集与网络阶段总预算。启动发现、报告导出、通知及必要进程清理不计入严格墙钟承诺。
- Python 的网关、3 个公网 Ping、2 个 DNS 解析并发；DNS 与可选测速使用可结束的子进程。
- 原生/Node 的独立系统采集并发，随后网关、公网、DNS 与可选扫描并发。
- `--fast` 只跳过周边热点扫描，不偷偷减少 Ping 样本或省略报告字段。
- DNS 原生/Node 延迟包含系统解析命令启动开销，source 明确标记；不宣称与 Python 的纯解析计时完全同精度。
- 命令不可用、权限错误、超时、无有效统计不是 100% 丢包；只有实际测量才进入评分。
- 不默认下载测速，`--speedtest` 才执行最多 1 MB 请求。

## 维护与验证

`portable/contract.json` 保存字段顺序、标签和建议文案；`core.js` 是 JXA/Node 共享的纯报告核心；`report.ps1` 是 Windows 原生实现；`parse.js` / `windows-collect.ps1` 解析采集结果。任何评分/文案修改都必须运行差异测试，不能只改其中一套。

```text
python -m unittest discover -s wifi-health-detector/tests -v
python -m unittest discover -s wifi-health-detector/integrations/enterprise-notification-bridge/tests -v
```

开发测试可用 `TEST_NODE`、`TEST_PYTHON` 和 `TEST_POWERSHELL` 指定解释器。Windows CI 使用系统 PowerShell 5.1；macOS CI 验证 JXA。测试包含 Unicode/引号/换行、报告差异、解释器空格路径、命令故障、进程树清理、并发屏障和无 Python 的 macOS 原生执行。此次开发在 macOS 完成实测，并使用临时 PowerShell 7.4.6 验证报告与进程控制逻辑；Windows 5.1、实际 WLAN 和企业权限策略仍需在部署机器或 Windows CI 验收。
