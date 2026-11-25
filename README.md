# liang-skill

面向 Claude Code、Codex 和兼容 Agent Skills 的宿主，提供 39 个中文 Skills，覆盖电脑操作、问题分析、知识库管理、Skill 制作、内容生产、传播诊断和产品品宣。

命名规则：统一 `liang-` 前缀 + 短功能词；完整内容家族使用 `liang-content-*`，独立诊断入口使用 `liang-*`；裸 `liang` 是意图模糊时的入口路由器。

## 发布范围与使用条件

`skills/` 包含全部 39 个入口及其脚本、模板、共享资源和第三方许可。本公开副本移除了个人内容项目、真实客户案例、账号实绩、私有知识库配置和本机注册表；本地 Git 历史不随公开副本发布。

- 内容家族共用 `liang-content`；首次使用建议安装整包，按需调用其中的入口。
- 纯文字工作流由 Agent 执行；脚本按功能需要 Python 3、Node.js、ffmpeg 等环境，具体要求见各 Skill。
- 录屏文字识别和剪映草稿相关功能面向 macOS；网页视频渲染需要 Playwright 与 Chrome，音乐分析和剪映导出另需各自的 Python 依赖。
- `liang-playbook` 和 `liang-transcript-mine` 需要使用者提供自己的语料、索引或数据源配置；公开仓库不附带私人知识库。
- 部分文档会提及 `dbs-*` 等外部 Skill。它们不随本仓库安装；未安装时说明缺失并采用当前宿主的等价能力，需要该外部能力的动作则保持待处理。
- 工作流定义、静态检查或合成样本测试通过，不代表平台采集、真实媒体工程和业务效果已经在你的环境中验证。

## 安装

从远端安装：

```bash
npx skills add elvinpancl/liang-skill
```

本机仓库开发态安装到 Claude 与 Codex：

```bash
bash scripts/install-local.sh          # 只预览
bash scripts/install-local.sh --apply  # 创建或刷新软链
```

装好后说对应触发词即可命中。

`liang-computer-use` 允许按任务自动选择，无须先调用 `/liang`。若需要把它设为电脑操作的默认规范，在宿主全局规则中加入：「已授权任务需要操作网页或桌面 App 时，默认读取并使用 `liang-computer-use`；纯检索、API 和文件处理不触发，已有权限边界不变。」宿主须能读取相应规则和 Skill 才能采用。安装不是常驻服务，也不会自动授予电脑控制权限；现有会话是否热加载以宿主实际行为为准。

## 当前 skills

| skill | 做什么 | 触发词举例 |
|---|---|---|
| `liang` | 入口路由器：不确定用哪个工具时分发 | 「/liang」「我该用哪个 liang 工具」 |
| `liang-computer-use` | 电脑操作：选用独立浏览器或桌面环境，默认禁止接管用户桌面、操作后回读；支持任务中自动使用 | 「操作这个 App」「打开已登录的页面」「在电脑上帮我……」 |
| `liang-clarify` | 问题澄清：比较正反最强论证，定位关键分歧并形成判断 | 「帮我想清楚」「澄清这个决定」 |
| `liang-coffee-talk` | 专家圆桌：召集 3-5 位专家并行讨论，逐轮收敛成一个判断，落盘方案卡 | 「开圆桌」「召集专家」「coffee talk」 |
| `liang-deconstruct` | 苏格拉底式命题解构：多轮只问不答，拆到不可再拆的公理，落盘带证据标记的解构档案 | 「拆到底」「这个观点站不站得住」「第一性原理」 |
| `liang-persona` | 从购买处境、心理张力和身份跃迁提炼目标付费人群的一句话画像 | 「核心客户是谁」「一句话说透这群人」「处境＋描述」 |
| `liang-playbook` | 行业打法挖掘：穷尽本地四层语料，按证据分级补料，六道闸门通过后生成 7 模块候选卡 | 「挖一下这个行业的打法」「补一张行业卡」 |
| `liang-knowledge` | 文件夹知识库：建立知识库导航与 Agent 入口，负责收录新资料、查找原文、判断当前版本、健康检查和导航瘦身 | 「把这个文件夹建成知识库」「从知识库找一下」「检查一下知识库」 |
| `liang-skill-maker` | 做 Skill、改 Skill：新做先问清它管什么、不管什么，交方案等确认后才写文件，拿真任务试跑并报告验证到第几级；带和不带各跑一次，删掉模型本来就会的部分 | 「做个 Skill」「把这件事存成 Skill」「这个 Skill 老出错，帮我修」 |
| `liang-transcript-mine` | 直播录音与抖音逐字稿的每周增量挖掘：脚本列队、子代理分块读全文、按卡号模块出打法／洞见／方法候选，控制 token | 「跑本周增量挖掘」「录音提取」「挖新打法洞见」 |
| `liang-drift` | 改稿漂移检测：给两版稿子算 0-100 内容漂移分 + 分档动作建议 | 「这两版差多少」「改稿漂移」「比一下两稿」 |
| `liang-hook` | 视频开头守门：素材诊断、原型替换、证据分级和预测转介包 | 「优化开头」「给这稿子配个开头」 |
| `liang-promo-plan` | 产品品宣视频拍前规划：按能力层拆集、贯穿案例与模拟数据、每个镜头标明身份的录屏清单 | 「做产品宣传片规划」「写录屏清单」 |
| `liang-promo-footage` | 录屏取证：抽帧加文字识别、实录对照、按时间点导出配图、打码清单 | 「录屏取证」「核对录屏素材」「出打码清单」 |
| `liang-promo-edit` | 品宣剪辑：镜头索引、剪辑台本、脚本切粗剪、旁白排成剪映可导入的字幕、成片逐秒扫打码、用成片反向复盘 | 「切粗剪」「写剪辑台本」「成片发布前检查」 |
| `liang-promo-article` | 品宣文章：痛点开场、第三方视角、讲能力不讲操作，每句对得上画面，成稿过机器自检 | 「写品宣文章」「把录屏写成公众号」 |
| `liang-wechat-layout` | 公众号排版：定稿排成固定样式（蓝色斜块加橙色重点，或紫色卡片版式），全行内样式，预览页一键复制粘贴进后台，`--watch` 改稿自动刷新，只加标记不改字 | 「公众号排版」「排成公众号」 |
| `liang-promo-motion` | 片头、片尾、叠加动画：语义分镜表、旁白时间表驱动的单文件 HTML、节奏检查、逐帧导出 MP4 或透明 ProRes 并验收 | 「做片头」「片头动画」「透明叠加动画」 |
| `liang-promo-beat` | 音乐卡点展示片：逐帧音乐分析与小节剪接、录屏取证、HyperFrames 动效组件库做底片、卡点回测、生成视频穿模筛查、Codex 任务书协作 | 「卡点视频」「音乐卡点」「踩点剪辑」 |
| `liang-promo-jianying` | 剪映可编辑工程：按计划和品牌包生成草稿（运镜关键帧、原生转场、说明、画中画），打码切片、回读校验、布局预览、安全安装 | 「做成剪映工程」「生成剪映草稿」 |
| `liang-content` | 内容生产与校准总入口 | 「内容闭环」「内容系统」 |
| `liang-content-init` | 初始化项目、状态和基础文件 | 「初始化内容项目」「首次使用」 |
| `liang-content-learn` | 从对标账号导入脚本与数据，提炼模式 | 「学这个账号」「导入对标」 |
| `liang-content-seed` | 围绕用户输入深挖选题并生成 draft | 「找选题」「启动种子」 |
| `liang-content-logic` | 叙事连续性诊断：衔接、密度和口播卡点 | 「检查叙事逻辑」「哪里会划走」 |
| `liang-resonate` | 发布前五维共鸣诊断与具体删改方向 | 「这稿戳中人吗」「共鸣点在哪里」 |
| `liang-spread` | 传播情绪、有效立场与传播入口解码 | 「为什么这个能传播」「打中了什么情绪」 |
| `liang-content-score` | 单稿盲打分，只输出不写文件 | 「给这稿子打分」「score this」 |
| `liang-predict` | 内容预测：子代理盲打分 + 四档概率分布押注，预测卡落笔即封（首次自动建档） | 「启动预测」「打分这篇」 |
| `liang-content-shoot` | 登记已拍摄，建立视频目录并进入发布队列 | 「拍了」「录完了」 |
| `liang-publish` | 登记已发布，只写元数据不动预测段 | 「已发布」「刚发完」 |
| `liang-retro` | 数据回收复盘：对账预测，观察记进账本 | 「复盘」「数据来了」 |
| `liang-content-persona` | 从评论和复盘数据刷新账号现有受众画像 | 「我的观众是谁」「更新 persona」 |
| `liang-bump` | 评分标准升级：子代理盲重打校准池 + 排序一致性检查，不过就拒 | 「升级评分标准」「公式不准了」 |
| `liang-content-recommend` | 按当前评分标准推荐候选选题 | 「推荐选题」「下一篇做什么」 |
| `liang-content-trends` | 抓取热点源，去重后写入候选池 | 「抓热点」「今天有什么可做的」 |
| `liang-status` | 预测闭环看板：待复盘、校准进度，只读无副作用 | 「预测状态」「看板」 |
| `liang-content-migrate` | 导入旧内容项目或升级 schema | 「导入旧内容项目」「升级 state」 |
| `liang-score-blind` | 内容闭环内部盲评分入口 | 由预测、升级流程内部调用 |

## 封存 hook（可选但推荐）

`liang-predict` 自带一个 PreToolUse hook，把预测卡封存段的「不可改」从自律升级成机器强制：任何 Edit / Write 触到 `bets/*.md` 里的 `## 预测` 段都会被拦下；header 登记、复盘段追加、整段追加 `## 预测 v2` 照常放行。注册方法：在 `~/.claude/settings.json` 加一条（路径按你的实际安装位置调整）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          { "type": "command", "command": "bash ~/.claude/skills/liang-predict/tools/seal-guard.sh", "timeout": 3 }
        ]
      }
    ]
  }
}
```

不注册也能用整个预测闭环，只是封存靠自觉。纯格式修复确需动封存段时，用 `LIANG_SEAL_BYPASS=1` 单次旁路（stderr 会留痕）。

## 自测

```bash
bash skills/liang-drift/tools/drift_test.sh          # 漂移引擎行为测试，应全过
bash skills/liang-predict/tools/seal_guard_test.sh   # 封存 hook 放行/拦截边界测试，应全过
bash skills/liang-predict/tools/seal_guard_test.sh skills/liang-content/hooks/prediction-immutability.sh
python3 skills/liang-hook/tools/validate.py          # 开头协议、案例证据与转介契约静态检查
bash skills/liang-content/scripts/diff_pct_test.sh   # 内容校准数值工具测试
bash skills/liang-promo-footage/scripts/selftest.sh  # 录屏取证脚本：抽帧、新增文字去重、打码扫描
bash skills/liang-promo-edit/scripts/selftest.sh     # 品宣剪辑脚本：索引、粗剪、排时、开头渲染、发布前检查、复盘
bash skills/liang-promo-article/scripts/check_article_test.sh  # 品宣文章自检脚本
bash skills/liang-wechat-layout/scripts/selftest.sh  # 公众号排版：解析、编号、重点、图片嵌入与占位、转义、主题、卡片版式、实时预览、静态检查
bash skills/liang-promo-motion/scripts/selftest.sh   # 片头动画：节奏检查、构建、样帧、MP4 与透明导出验收
PYTHON=<venv>/bin/python bash skills/liang-promo-beat/scripts/selftest.sh      # 卡点片：音乐分析、剪接、回测、筛查、组件库构建
PYTHON=<venv>/bin/python bash skills/liang-promo-jianying/scripts/selftest.sh  # 剪映草稿：打码切片、构建、回读校验、预览、安装前检查
node scripts/validate-skill-tree.mjs                 # 全 skill 结构、资源与许可检查
```

## 说明

- 通用 skill 各自自包含；内容家族采用「薄入口 + 家族共享核心」。共享资源位于 `skills/liang-content/`，运行时先从同一安装根目录定位核心。
- `liang-predict/publish/retro/bump/status` 在没有 `.liang-content-state.json` 时保持原轻量闭环；检测到该文件后进入完整内容校准模式。
- 完整内容项目使用 `.liang-content-state.json`、`scorecard.md`、`ledger.md`、`bets/`。
- 旧 `.cheat-state.json` 内容项目不会自动改写；使用 `liang-content-migrate` 先 dry-run、备份，再显式导入。
- `liang-resonate` 与 `liang-spread` 固定使用五个经典传播理论；理论框架位于 `skills/liang-content/references/resonance-framework.md`，业务封装不得新增自创维度。
- `liang-hook` 的公开原型用于生成和诊断；公开版不附带个人验证集，不据此声称命中率、业务效果或因果。
- 新增或重构 skill 时按 `docs/skill-template.md` 标注证据等级、数字口径、状态转介和验证契约。

## 授权

本项目采用非商业许可公开源码，不属于允许商业使用的开放源代码许可。

本仓库原创部分以 [PolyForm Noncommercial 1.0.0](LICENSE) 授权：个人学习、研究、自用和非商业分享自由，保留出处即可；任何商业用途（含卖课、付费社群打包分发、内置进商业产品或服务）需先取得书面授权。

Required Notice: Copyright 2026 Chunliang Pan (https://github.com/elvinpancl/liang-skill)

第三方资源继续适用各自许可，包括 XBuilderLAB 与 xhs-analytics 的 MIT 资源、video-shotcraft 的 Apache 2.0 资源，以及 xkcd 字体的 CC BY-NC 3.0。来源、版权声明和完整许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
