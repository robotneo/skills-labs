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