# Wi-Fi Health Detector Skill

无线网络健康检测 Skill，用于在 macOS 和 Windows 上检测当前 Wi-Fi 参数、网关时延、丢包率、同信道干扰数量，并输出健康评分和优化建议。

## 特性

- 支持 macOS 和 Windows
- 仅依赖 Python 3.7+，无第三方库
- 输出 Wi-Fi 核心参数：SSID、频段、信道、频宽、信号强度、协商速率、IP、网关、MAC、时延、丢包率
- 输出健康评分和优化建议
- 支持敏感信息打码、指定网卡、JSON/CSV 输出

## 安装

### macOS

```bash
WIFI_HEALTH_DETECTOR_REPO="https://github.com/robotneo/skills-labs.git" \
bash -c "$(curl -fsSL https://raw.githubusercontent.com/robotneo/skills-labs/main/wifi_health_detector/install.sh)"
```

### Windows

下载并运行：

```text
https://raw.githubusercontent.com/robotneo/skills-labs/main/wifi_health_detector/install.bat
```

发布到 GitHub 前，把 `robotneo` 替换成真实用户名。

## 使用

```bash
python3 main.py
python3 main.py --interface en0
python3 main.py --mask
python3 main.py --json result.json
python3 main.py --csv result.csv
```

在 Codex 或其他 AI 助手中，用户可以说：

- 检测 WiFi 质量
- 查看无线网络状态
- 查询 Wi-Fi 参数
- 看一下无线网络是否健康

## 权限说明

Wi-Fi 参数、网关 ping、丢包率和周边热点扫描需要读取本机真实网络接口。若在沙箱中运行，网络质量指标可能不准确；请使用本机权限运行。
