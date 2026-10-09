# Wi-Fi Health Detector

在 macOS / Windows 本机检测 Wi-Fi，按 Python → 系统原生 选择可用引擎。企业通知组件随包提供，默认关闭。

下载发布 ZIP，解压后将整个 `wifi-health-detector` 目录交给 Agent 的技能管理器，或放入它支持的技能目录。无需在线安装脚本，不要只复制 `SKILL.md`。

- macOS：`./run.sh`
- Windows：`run.bat`
- 快速检测：追加 `--fast --budget 15`
- 本地链路检测：追加 `--no-public-test --no-notify`
- 其他参数、安全边界和通知入口见 [SKILL.md](SKILL.md)。

开发者在仓库根目录运行 `python scripts/package_wifi_skill.py` 构建发布包。发布包包含所有检测与通知运行代码、操作指引和元数据；测试、缓存和开发 README 保留在源码中。
