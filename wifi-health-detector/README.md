# Wi-Fi Health Detector Skill

无线网络健康检测 Skill 2.5，支持 macOS 10.12+（Intel/Apple Silicon）和 Windows 10/11（中英文系统）。采用原生启动器和统一 Python 核心，能够区分 Python/权限/系统命令问题与真实 Wi-Fi 故障。

## 特性

- 支持 macOS 10.12+、Windows 10/11
- 仅依赖 Python 3.7+，无第三方库
- 完整输出系统、适配器、连接、射频、链路、IP、本地质量、公网质量和诊断字段
- 不可获取字段保留原因，不用“未知”或虚假默认值扣分
- 分项评分、数据置信度和基于证据的优先级建议
- 支持敏感信息打码、自动/指定网卡、稳定 JSON 2.0 和完整 CSV
- 默认使用阿里公共 DNS、腾讯 Public DNS、百度和淘宝进行多目标国内公网检测，1 MB 下载测速需显式开启
- 只输出固定 Markdown 仪表盘，始终按“📶 报告、⭐ 核心参数、🏠 本地质量、🌐 公网质量、🧭 诊断建议”排列
- 核心表固定保留 18 项独立参数，包括系统版本、芯片架构、MAC、Wi-Fi 连接、射频、速率、网关、公网和安全信息；缺失值也不隐藏
- 默认显示 Wi-Fi 名称；只有用户明确要求脱敏或公开分享时才使用 `--mask`
- Windows 显示系统提供的发送/接收 PHY 速率；macOS 未提供接收速率时保留固定行并标明原因，不做推算
- macOS 通过完整 `system_profiler` 获取当前信道宽度；Windows 优先读取 `netsh`，缺失时解析 Native Wi-Fi BSS 信息元素
- Markdown 只有 `--view summary` 标准视图；程序会在输出前校验区段和行数，禁止追加详细区段。交给企业通知 Bridge 时，JSON 是唯一数据源，Bridge 会确定性重建整份 Markdown 并全文比对；任何 Agent 新增、删减、重复、重排、翻译或改写格式都会被拒绝

## 安装

### macOS

```bash
WIFI_HEALTH_DETECTOR_REPO="https://github.com/robotneo/skills-labs.git" \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/robotneo/skills-labs/main/wifi-health-detector/install.sh)"
```

### Windows

下载并运行：

```text
https://raw.githubusercontent.com/robotneo/skills-labs/main/wifi-health-detector/install.bat
```

发布到 GitHub 前，把 `robotneo` 替换成真实用户名。

## 使用

macOS：

```bash
./run.sh
./run.sh --interface en0 --mask
./run.sh --json result.json --csv result.csv
./run.sh --view summary
```

Windows：

```bat
run.bat
run.bat --language zh --mask
run.bat --json result.json --csv result.csv
run.bat --view summary
```

通用参数：`--view summary` 为唯一 Markdown 视图，`--speedtest` 开启吞吐测试，`--no-public-test` 仅检测本地链路，`--timeout` 设置超时，`--verbose` 保留机器数据中的诊断警告。`main.py` 仅作为已知 Python 可用时的兼容入口。JSON/CSV 是显式机器数据导出，始终包含全部字段，但不会扩展 Markdown 报告。

在 Codex、Claude Code、WorkBuddy、OpenClaw 或其他兼容 Agent 中，启动器成功后必须把 stdout 原样作为完整最终答复，不得添加前言、代码围栏、摘要、解释或结论，也不得删除、合并、翻译或重排报告内容。

企业通知组件已内置于 `integrations/enterprise-notification-bridge`，只需安装 `wifi-health-detector` 一个 Skill。默认关闭通知，不安装 DWS，也不触发登录。首次报告后可通过单独的后续交互选择是否启用，设置结果保存在原有 Bridge 配置位置，更新 Skill 不会覆盖组织和收件人配置。

需要通知时，从内置组件目录运行 `run.sh status`（Windows 使用 `run.bat`），按 [操作指引](integrations/enterprise-notification-bridge/OPERATIONS.md) 配置。`disable` 保存关闭选择并保留已有组织和人员配置；`enable --platform dingtalk --provider auto` 启用渠道。完整的宿主原生能力优先；钉钉原生能力不足时才检查 DWS，缺失时在获准的设置流程中安装，首次或授权失效时登录。飞书和企业微信使用宿主声明的能力，不能用 DWS 代替。空收件人不会发送。

发现顺序为显式 `ENTERPRISE_NOTIFICATION_BRIDGE` JSON 命令数组、内置组件、旧版相邻目录。通知失败不改变标准报告和检测退出状态。`--no-notify` 仅跳过本次通知。安装脚本会复制整个 Skill 目录，包括内置组件；无需另行安装桥接 Skill。

在 Codex 或其他 AI 助手中，用户可以说：

- 检测 WiFi 质量
- 查看无线网络状态
- 查询 Wi-Fi 参数
- 看一下无线网络是否健康

## 权限说明

Wi-Fi 参数、网关 ping、丢包率和周边热点扫描需要读取真实网络接口。沙箱或普通权限可能隐藏部分字段；报告会明确显示“不可用”和原因。终端默认展示完整 SSID、BSSID、MAC 和地址；仅在用户明确要求脱敏或公开分享时使用 `--mask`。

macOS 若系统 `python3` 报 `invalid active developer path`，请直接运行 `run.sh`。启动器会优先寻找独立 Python；若仍不可用，会提示安装 Python，而不会误报 Wi-Fi 未连接。
