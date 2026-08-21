# Wi-Fi Health Detector Skill

无线网络健康检测 Skill 2.1，支持 macOS 10.12+（Intel/Apple Silicon）和 Windows 10/11（中英文系统）。采用原生启动器和统一 Python 核心，能够区分 Python/权限/系统命令问题与真实 Wi-Fi 故障。

## 特性

- 支持 macOS 10.12+、Windows 10/11
- 仅依赖 Python 3.7+，无第三方库
- 完整输出系统、适配器、连接、射频、链路、IP、本地质量、公网质量和诊断字段
- 不可获取字段保留原因，不用“未知”或虚假默认值扣分
- 分项评分、数据置信度和基于证据的优先级建议
- 支持敏感信息打码、自动/指定网卡、稳定 JSON 2.0 和完整 CSV
- 默认轻量 DNS/公网检测，1 MB 下载测速需显式开启
- 默认输出固定 Markdown 仪表盘和完整详情；`--view summary` 展示核心参数、本地质量、公网质量与建议

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

通用参数：`--view full|summary` 控制完整或摘要视图，`--speedtest` 开启吞吐测试，`--no-public-test` 仅检测本地链路，`--timeout` 设置超时，`--verbose` 保留诊断警告。`main.py` 仅作为已知 Python 可用时的兼容入口。JSON/CSV 始终包含全部字段，不受视图参数影响。

在 Codex 或其他 AI 助手中，用户可以说：

- 检测 WiFi 质量
- 查看无线网络状态
- 查询 Wi-Fi 参数
- 看一下无线网络是否健康

## 权限说明

Wi-Fi 参数、网关 ping、丢包率和周边热点扫描需要读取真实网络接口。沙箱或普通权限可能隐藏部分字段；报告会明确显示“不可用”和原因。终端默认展示完整 SSID、BSSID、MAC 和地址，公开分享前请使用 `--mask`。

macOS 若系统 `python3` 报 `invalid active developer path`，请直接运行 `run.sh`。启动器会优先寻找独立 Python；若仍不可用，会提示安装 Python，而不会误报 Wi-Fi 未连接。
