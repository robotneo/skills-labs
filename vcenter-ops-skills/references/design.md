# 设计规范

格式：标准 `AgentSkills` 形态
模式：`SKILL.md` + `Python`
结构：

✅ SKILL.md = 唯一入口（metadata + 说明）
✅ Python 全部放入 scripts/
✅ 数据 / 模板归档到 assets/
✅ 文档沉淀到 references/
✅ 后续可直接接 vCenter / 钉钉

目录：

```markdown
skill-vcenter-provision/
├── SKILL.md                # ✅ 核心入口（YAML + 文档）
├── init.sh                 # ✅ 初始化脚本
│
├── scripts/                # ✅ 所有执行逻辑
│   ├── main.py
│   ├── core/
│   │   ├── planner.py
│   │   ├── ip_allocator.py
│   │   └── host_scheduler.py
│   │
│   └── integrations/
│       └── ping.py
│
├── assets/                 # ✅ 数据 & 模板
│   ├── ip_pool.yaml
│   ├── hosts.yaml
│   └── output_template.py
│
├── references/             # ✅ 扩展文档
│   └── design.md
│
└── requirements.txt
```

### 项目初始化

在开始开发前，需要运行 `init.sh` 脚本来初始化项目结构：

1.  **包初始化**：自动在 `scripts/` 和 `assets/` 目录下的所有子目录中创建 `__init__.py` 文件，确保 Python 能够正确识别这些目录为包。
2.  **执行命令**：
    ```bash
    bash init.sh
    ```