# liang-transcript-mine 公开版

这是需要配置自有语料的增量挖掘工具，不附带作者的逐字稿、母版、订阅账号或私人运行记录。公开版只验证本地合成数据上的配置、扫描与队列行为；未验证真实 Get 笔记账户访问、Agent 提取质量或云端发布。

## 配置

需要 Python 3.10 以上。普通 TXT / Markdown 不需要额外 Python 包；DOCX 读取使用 macOS `textutil`。本地发布锁使用 POSIX `fcntl`，原生 Windows 尚不支持。

1. 准备已有知识库目录，将 `assets/config.example.json` 复制为该目录下的 `liang-transcript.json`。
2. 填写配置中的源文件 glob、三份母版和两份处理契约。所有配置路径相对知识库根目录，必须位于其中。源文件只包含获准处理的原始逐字稿，不匹配候选、摘要或生成结果。
3. 设置环境变量；脚本目录取本 Skill 的实际安装位置。

```bash
export LIANG_KB_ROOT="/path/to/your/knowledge-base"
# 可选：配置不放在知识库根目录时使用
export LIANG_TRANSCRIPT_CONFIG="/path/to/your/knowledge-base/liang-transcript.json"
S="/path/to/liang-transcript-mine/scripts"
python3 "$S/run_init.py" --status
python3 "$S/run_init.py"
python3 "$S/source_queue.py" build
python3 "$S/source_queue.py" next --n 3
```

未配置根目录、配置无法读取、母版或契约缺失都会明确退出；不会回退到作者目录。`--status` 不创建运行目录或锁文件。首次没有可识别的发布日期时保持候选模式，不推定用户授权发布。

三份母版格式：

- `tactics`：`### 1. 卡片标题`，每卡包含 `#### 1. ...` 至 `#### 7. ...`。模块名称参考 `scripts/card_locator.py` 的 `TACTIC_MODULES`。
- `insights`：`#### 洞见 1｜标题`，可用 `##### **判断**`、`逻辑`、`边界`、`动作`、`怎么讲` 分段。
- `method`：`## 章节标题`，子节使用 `### 小节标题`。

母版应使用真实的已有知识，缺少时先建立相应资料；不要用空白模板假装已有知识库。`contracts.正文写法` 规定草稿写法与读者验收，`contracts.来源与发布` 规定来源授权、目标版本、发布渠道和提交条件。公开仓库不替用户授权外部发布。

可选配置：`carry_since` 为兼容候选格式的起始日期；`speaker_aliases` 为讲者名称到短名的映射；`speaker_paths` 为来源路径片段到讲者名称的映射。均不配置时不会使用作者的历史名单。

## 增量扫描与提交边界

内置 `scripts/check_source_increment.py` 是公开版独立实现的通用扫描器。读取 `source_patterns`，跳过软链，仅支持 TXT、Markdown、DOCX。它把当前文件哈希与 `<workspace_dir>/scratchpad/定时更新/processed_source_hashes.tsv` 比较，输出 `new`（未处理）、`changed`（内容变化）、`stale`（处理标准变化）、`unchanged`（未变化）。基线必须含 `relative_path`、`sha256`、`extractor_version` 三列，路径相对工作目录。不存在基线时全部视为未处理；格式不符时明确失败。

扫描器和队列不写基线、不把来源自动标成已发布。正式合并和云端发布需用户自己的集成及授权；本公开版不附带作者的发布脚本、状态提交脚本或 `reader_gate.py`。读者验收可按公开的脱敏提示词执行。只有已完成实际验收的来源才可由获准的发布者更新基线。

## 可选 Get 笔记输入

不使用 Get 笔记时直接跳过 `getnote_fetch.py`，处理本地逐字稿即可。使用时在本地配置增加：

```json
{
  "getnote": {
    "topic_id": "YOUR_TOPIC_ID",
    "accounts": {"你已订阅的账号全名": "本地短名"}
  }
}
```

凭据由运行环境提供 `GETNOTE_API_KEY` 和 `GETNOTE_CLIENT_ID`；不写进仓库或命令行参数。代码不读取作者的钥匙串。`source_patterns` 还需覆盖 `语料库/*/抖音研究/*/逐字稿/*_原文版.md`。账号与主题应由用户确认，接口当前权限以真实账户为准。调用仅请求已有订阅内容，不创建或删除远端笔记。

```bash
python3 "$S/getnote_fetch.py" list
python3 "$S/getnote_fetch.py" fetch
```

## 本地检查

```bash
python3 -B -m unittest discover -s skills/liang-transcript-mine/tests -v
```

测试仅使用自动清理的合成知识库，不访问网络或真实账户。
