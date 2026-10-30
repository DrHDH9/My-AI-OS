# notes/ — 活跃层

**这里放什么**：一条事一个文件。所有"需要以后的 AI 知道"的东西都在这里。

**什么时候填**：`mem.py add` 自动写进来。**不要手动建文件**——
手写会绕过校验、绕过正文哈希基线、绕过审计流水，`check` 也查不出谁动过。

```
python mem.py add --type 决策 --topic 存储 --title "选 SQLite" \
  --body "结论：..." --why "为什么，以及否掉了什么"
```

**文件命名**：`YYYY-MM-DD-类型-主题.md`。同一天同类型同主题会自动加 `-2`。

**谁读**：
- `brief` 会挑最新的和相关度最高的几条进简报（默认 5 条）
- `search` 全文检索这里
- `tier` 在条数超过 `config.json` 的 `active_limit` 时，把最旧的移到 `cold/`

**五种类型**（在 `config.json` 和 `mem.py` 的 `TYPES` 里登记过才能用）：
事实 / 经历 / 决策 / 经验 / 待办。另有一个 `摘要`，由 `consolidate` 生成。

---

## 一条笔记长什么样

```
---
topic: 存储
type: 决策
date: 2026-10-29
recorded: 2026-10-29T21:00:00+08:00
scope: default
source: hand
valid_from: 2026-10-29
valid_to: -
invalid_reason: -
superseded_by: -
supersedes: -
---

# 选 SQLite 不选 Postgres

## 结论

只在一台机器上跑，SQLite 够用且零运维。

## 为什么

省掉一个要维护的服务；并发量根本到不了需要 Postgres 的程度。

## 否掉了什么

Postgres：为一个每天几十次写入的场景维护连接池和备份任务，不值。
```

**正文永远不重写。** 记错了或改主意了，用 `--supersede 旧文件名` 新起一条，
旧的那条只改 frontmatter 里的三行（`valid_to` / `invalid_reason` / `superseded_by`）。
正因为正文不许动，`check` 才能发现"谁偷偷改了内容"。
