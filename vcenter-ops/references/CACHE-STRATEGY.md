# 会话缓存策略详解

> 从 SKILL.md 展开的缓存机制完整说明。

## 问题

vCenter API 全量查询 ~30s，返回 250KB+ JSON，直接喂给模型消耗大量 token。

## 解决方案

首次查询保存本地 JSON，后续按需提取字段。

## 缓存规则

| 场景 | 操作 | 耗时 | Token |
|------|------|------|-------|
| 首次查询 | API + 保存 | ~30s | 仅摘要 |
| 后续查询 | 读本地 JSON | <1s | 仅提取字段 |
| 用户说"刷新" | 重新 API | ~30s | 仅摘要 |
| 写操作 | 直接 handler.py | 正常 | 正常 |

## 执行流程

### Step 1: 检查缓存

```bash
cd skills/vcenter-ops && python3 scripts/cache_manager.py --status
```

### Step 2: 判断

- 有缓存 → Step 3 按需读取
- 无缓存 → Step 2a 刷新

### Step 2a: 首次刷新

```bash
cd skills/vcenter-ops && python3 scripts/cache_manager.py --refresh
```

> ~30s，告诉用户"正在巡检..."

完成后输出摘要：
```bash
python3 scripts/cache_manager.py --summary
```

摘要示例：
```json
{"status":"ok","datacenters":["Datacenter"],"clusters":["MD1200","SC4020","共享存储","GPU","vSAN-A"],
"templates":8,"datastores":55,"networks":8,"hosts":{"total":45,"available":30,"maintenance":14},"vms":{"total":360}}
```

### Step 3: 按需读取

```bash
# 各类别
python3 scripts/cache_manager.py --section templates
python3 scripts/cache_manager.py --section datastores --top 10
python3 scripts/cache_manager.py --section hosts --cluster "共享存储"
python3 scripts/cache_manager.py --section networks
python3 scripts/cache_manager.py --section vm_ips

# 搜索 VM
python3 scripts/cache_manager.py --search "nginx"
```

## 关键规则

1. **会话级**：`/tmp/vc_session_cache.json`，`/new` 不保留
2. **不自动过期**：只有用户说"刷新"才重查
3. **写操作不受影响**：克隆/删除仍直接调用 handler.py
4. **数据一致性**：执行写操作后建议提示用户刷新
5. **按需提取**：不加载全量 250KB 到上下文

## 缓存文件

| 文件 | 路径 | 大小 | 用途 |
|------|------|------|------|
| 全量数据 | `/tmp/vc_session_cache.json` | ~170KB | VM/宿主机/存储等 |
| 元信息 | `/tmp/vc_session_meta.json` | ~1KB | 缓存时间、统计 |

## 排除 IP 文件

| 文件 | 路径 | 用途 |
|------|------|------|
| 排除列表 | `/tmp/exclude_ips.txt` | IP扫描排除（341个IP） |

使用 `--exclude-file` 传参（避免命令行过长）。
