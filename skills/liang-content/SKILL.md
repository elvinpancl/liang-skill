---
name: liang-content
description: liang-skill 的内容生产与校准总入口。负责在初始化、对标学习、选题、叙事逻辑、共鸣诊断、传播情绪解码、盲打分、预测、拍摄、发布、复盘、受众画像、规则升级、推荐、热点与状态迁移之间分发。触发词：「内容闭环」「内容系统」「初始化内容项目」「我该走哪个内容 skill」。明确说出「检查叙事逻辑」「共鸣诊断」「传播解码」「启动预测」「复盘」「抓热点」时直接走对应子 skill。
argument-hint: [一句话说明当前要做什么]
allowed-tools: Read, Glob, Skill, Bash(test:*)
---

# liang-content

把内容创作变成可校准闭环：先写判断，再看结果，再让规则随完整样本演化。

## 适用范围

- 处理：内容项目建档、素材与选题、叙事逻辑、共鸣与传播机制、盲评分、预测、发布节奏、实绩复盘和规则迭代。
- 不处理：只改开头走 `/liang-hook`；只比较两版稿走 `/liang-drift`。
- 用户意图命中多个阶段：暂停，只问当前稿件处于「选题、成稿、已拍、已发、待复盘」哪一段。

## 三条硬边界

1. 预测必须在看到实绩前写完，`bets/*.md` 的预测段落笔即封。
2. 评分通道只读稿件与 `scorecard.md`，禁止读取 `ledger.md`、`bets/`、`audience.md`、历史结果和证据等级。
3. 规则升级必须全量重打校准池并检查排序，不接受为了让新公式通过而下调门槛。

详细协议按任务读取 `references/`，不要一次性加载全部资料。

## 状态判定

依次检查当前项目：

1. 有 `.liang-content-state.json`：走完整模式。
2. 只有旧 `.cheat-state.json`：先转 `/liang-content-migrate`，不得直接覆盖旧状态。
3. 有 `scorecard.md`、`ledger.md` 或 `bets/`，但没有状态文件：这是 liang v1 轻量模式，现有 `/liang-predict`、`/liang-publish`、`/liang-retro`、`/liang-bump`、`/liang-status` 继续可用。
4. 都没有：转 `/liang-content-init`。

## 路由

| 当前诉求 | 调用 |
|---|---|
| 首次建档、选择内容形态、创建项目骨架 | `/liang-content-init` |
| 导入对标账号、拆脚本规律 | `/liang-content-learn` |
| 从经历或主题长出一个选题与草稿 | `/liang-content-seed` |
| 检查段落衔接、信息密度与口播断点 | `/liang-content-logic` |
| 发布前检查核心机制与五维共鸣 | `/liang-resonate` |
| 解码内容激活的情绪、立场与传播入口 | `/liang-spread` |
| 只打分，不立预测卡 | `/liang-content-score` |
| 成稿盲评分并立预测卡 | `/liang-predict` |
| 登记已拍并核对拍摄稿漂移 | `/liang-content-shoot` |
| 登记发布链接与平台 ID | `/liang-publish` |
| 回收数据、核对预测、沉淀观察 | `/liang-retro` |
| 从评论与复盘派生受众画像 | `/liang-content-persona` |
| 升级评分公式或重校 bucket | `/liang-bump` |
| 从候选池选一稳一实验 | `/liang-content-recommend` |
| 抓取热点并补候选池 | `/liang-content-trends` |
| 查看进度、buffer 与待复盘 | `/liang-status` |
| 导入旧状态或升级 schema | `/liang-content-migrate` |

`/liang-score-blind` 是内部隔离评分器，主对话不得把它当用户入口。

## 共享资源

- `references/`：盲预测、规则升级、状态、候选池、节奏、数据源以及传播理论协议。
- `assets/templates/`：项目文件模板。
- `assets/starter-rubrics/`：各内容形态的冷启动评分卡。
- `adapters/`：B 站、抖音、小红书、LinkedIn、Whisper 与热点源适配器。
- `hooks/`：预测不可变、会话状态与被动日志。
- `migrations/`：状态 schema 版本链。
- `scripts/`：稿件差异与校准曲线工具。

## 验证契约

- 所有公开入口目录名与 frontmatter `name` 必须一致。
- 完整模式引用的共享文件必须存在。
- 盲评分 prompt 不得包含实绩、倍率、档位、案例结果或 `liang_handoff.evidence_level`。
- 预测不可变 hook 的阻断退出码必须为 `2`。
