# Wi-Fi Health Detector

在 macOS / Windows 本机检测 Wi-Fi，按 Python → 系统原生 选择可用引擎。企业通知组件随包提供，默认关闭。

下载发布 ZIP，解压后将整个 `wifi-health-detector` 目录交给 Agent 的技能管理器，或放入它支持的技能目录。无需在线安装脚本，不要只复制 `SKILL.md`。

- macOS：`./run.sh`
- Windows：`run.bat`
- 快速检测：追加 `--fast --budget 15`
- 本地链路检测：追加 `--no-public-test --no-notify`
- 其他参数、安全边界和通知入口见 [SKILL.md](SKILL.md)。

技能以整个 `wifi-health-detector` 目录交付（包含检测与通知运行代码、操作指引和元数据），无构建步骤、运行时零三方依赖。根目录与 bridge 目录下的 `pyproject.toml` 仅供工具读取（声明名称、`requires-python >= 3.7`、零运行时依赖与单一版本源），不属于运行交付物，也无需 `pip install`。需要发布 ZIP 时，在仓库根目录用 `git archive --format=zip --prefix wifi-health-detector/ -o <产物> HEAD -- wifi-health-detector` 按 Git 跟踪清单导出，再排除任意层级的 `tests/`、开发用 `README.md`、`pyproject.toml`、`__pycache__/` 与 `*.pyc`，并保证 `run.sh` 在包内保留 0755 权限。持续集成的安全扫描作业（`.github/workflows/wifi-security-scan.yml`）用同一套跟踪清单加排除规则组装待扫描目录。
