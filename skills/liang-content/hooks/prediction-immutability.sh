#!/usr/bin/env bash
#
# liang-content / prediction-immutability —— 预测卡封存段的机器强制
#
# 挂在 Claude Code 的 PreToolUse(Edit|Write) 上，stdin 收工具调用的 JSON。
# 只管一件事：bets/ 下预测卡里的「## 预测」段（含 v2 等变体）落笔即封，
# 任何改动它的 Edit / Write 一律拦下。
#
# 放行的情况：
#   - bets/ 之外的一切文件
#   - 新建预测卡（Write 到不存在的路径）
#   - header（首个 ## 之前）的登记改动
#   - 复盘段的追加
#   - 以「## 复盘」为锚位整段插入「## 预测 v2」（不触碰既有封存段内容）
#
# 拦下的情况：
#   - Edit 的 old_string 与任一「## 预测」段（含标题行）有重叠
#   - Write 覆盖已存在的卡且任一封存段在新内容里不再原样出现
#
# 单次旁路（只留给纯格式修复）：LIANG_SEAL_BYPASS=1。
# 为兼容旧内容项目，也接受 LIANG_CONTENT_BYPASS_IMMUTABILITY=1。
#
# 依赖：bash 3+、python3（macOS 自带；与 liang-drift 的依赖一致，不需要 jq）。
# 退出码：0 = 放行；2 = 拦截（stderr 会被 Claude Code 喂回模型）。

set -uo pipefail

if [[ "${LIANG_SEAL_BYPASS:-0}" == "1" || "${LIANG_CONTENT_BYPASS_IMMUTABILITY:-0}" == "1" ]]; then
  cat > /dev/null || true  # 消费掉 stdin，别让上游 SIGPIPE
  echo "[liang-content] 封存旁路生效：本次放行。只该用于纯格式修复，改动会进 git 历史。" >&2
  exit 0
fi

input=$(cat || true)
[[ -z "$input" ]] && exit 0

# 粗筛：整个 JSON 里连 bets/ 字样都没有，必然与预测卡无关，直接放行，
# 不为每次 Edit/Write 都付一次 python 启动的开销。精确判断在下面的 python 里做。
case "$input" in
  *bets/*) : ;;
  *) exit 0 ;;
esac

PYCODE="$(cat <<'PY'
import json, os, sys


def sealed_spans(text):
    """返回所有「## 预测」段的 (起, 止) 字符区间，含标题行，止于下一个 H2 或文件尾。"""
    spans = []
    pos = 0
    start = None
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            if start is not None:
                spans.append((start, pos))
                start = None
            if line[3:].lstrip().startswith("预测"):
                start = pos
        pos += len(line)
    if start is not None:
        spans.append((start, len(text)))
    return spans


def block(reason):
    sys.stderr.write(
        "[liang-content prediction-immutability] 拦截：" + reason + "\n"
        "预测卡封存段落笔即封，一个字不许改。要重赌就以「## 复盘」行为锚位整段追加「## 预测 v2」；"
        "确属纯格式修复，用 LIANG_SEAL_BYPASS=1 单次旁路（会留痕）。\n"
    )
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # 解析不了就不拦——守门员不该把门框拆了

    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or ""
    if tool not in ("Edit", "Write") or not path.endswith(".md"):
        return
    parts = path.split("/")
    if "bets" not in parts[:-1]:
        return  # 精确判断：文件必须位于某个 bets/ 目录下

    if tool == "Write":
        if not os.path.isfile(path):
            return  # 新建预测卡
        try:
            old_text = open(path, encoding="utf-8").read()
        except Exception:
            return
        new_text = ti.get("content") or ""
        for a, b in sealed_spans(old_text):
            if old_text[a:b] not in new_text:
                block(f"Write 覆盖 {path} 会改动已封存的预测段。")
        return

    # Edit：old_string 的任一出现位置与任一封存段重叠即拦
    old_string = ti.get("old_string") or ""
    if not old_string:
        return
    try:
        text = open(path, encoding="utf-8").read()
    except Exception:
        return
    spans = sealed_spans(text)
    if not spans:
        return
    i = text.find(old_string)
    while i != -1:
        j = i + len(old_string)
        for a, b in spans:
            if i < b and j > a:
                block(f"这次 Edit 触到了 {path} 的封存预测段。")
        i = text.find(old_string, i + 1)


main()
PY
)"

printf '%s' "$input" | python3 -c "$PYCODE"
rc=$?
[[ $rc -eq 2 ]] && exit 2
exit 0
