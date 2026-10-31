#!/usr/bin/env bash
#
# drift_test.sh — behavioural test for drift.py
#
# Three scenarios that a line-level diff gets wrong (wide pass bands so the
# result holds across Levenshtein backends), plus engine contract cases:
#   A  same content reflowed from markdown into spoken short lines  -> [0, 30]
#   B  a completely different topic                                 -> [60, 100]
#   C  original plus a short appended outro (~20% more text)        -> [10, 30]
#   D  identical file                                               -> exactly 0
#   E  one character changed in a long draft                        -> [1, 3]
#   F  empty file vs non-empty                                      -> exactly 100
#   G  rapidfuzz and pure-Python backends give the same score
#      (skipped when rapidfuzz is not installed)
#
# Run:  bash drift_test.sh
# Exit: 0 all pass | 1 any fail
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIFT="$HERE/drift.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
pass=0 fail=0

score() { python3 "$DRIFT" "$1" "$2" 2>/dev/null; }

check() {
  local name="$1" orig="$2" rev="$3" lo="$4" hi="$5"
  local got
  if ! got="$(score "$orig" "$rev")"; then
    echo "  FAIL $name  engine exited nonzero"; fail=$((fail+1)); return
  fi
  if (( got >= lo && got <= hi )); then
    echo "  ok   $name  drift=$got in [$lo,$hi]"; pass=$((pass+1))
  else
    echo "  FAIL $name  drift=$got not in [$lo,$hi]"; fail=$((fail+1))
  fi
}

cat > "$WORK/a_orig.md" <<'EOF'
# 开场脚本 — 周更复盘

「我又卡在选题上了」——这大概是每个做内容的人每周都会说一次的话。

但真正的问题不在选题，在你没有一个能复用的判断标准。**关键动作**：先把上周数据摊开，再决定这周做什么。
EOF
cat > "$WORK/a_rev.md" <<'EOF'
我又卡在选题上了
这大概是每个做内容的人
每周都会说一次的话
但真正的问题不在选题
在你没有一个能复用的判断标准
先把上周数据摊开
再决定这周做什么
EOF
check "same-content-reflow" "$WORK/a_orig.md" "$WORK/a_rev.md" 0 30

cat > "$WORK/b_orig.md" <<'EOF'
# 关于早起

早起最难的不是闹钟响的那一刻，是前一晚决定几点睡。
把睡觉时间定下来，早起就不再需要意志力。
EOF
cat > "$WORK/b_rev.md" <<'EOF'
今天想聊聊手冲咖啡。
水温、粉的粗细、注水的节奏，每个变量都会改变味道。
新手最容易忽略的，是闷蒸那三十秒。
EOF
check "different-topic" "$WORK/b_orig.md" "$WORK/b_rev.md" 60 100

cat > "$WORK/c_orig.md" <<'EOF'
我一直以为努力就会有回报。后来才发现，拿到结果的人都很努力，但努力的人不一定拿到结果。
方向错了，越努力离目标越远。
EOF
cat > "$WORK/c_rev.md" <<'EOF'
我一直以为努力就会有回报。后来才发现，拿到结果的人都很努力，但努力的人不一定拿到结果。
方向错了，越努力离目标越远。
所以这周我先停下来，把方向想清楚再动手。
EOF
check "appended-outro" "$WORK/c_orig.md" "$WORK/c_rev.md" 10 30

check "identical-file" "$WORK/c_orig.md" "$WORK/c_orig.md" 0 0

python3 - "$WORK" <<'EOF'
import sys
from pathlib import Path
work = Path(sys.argv[1])
base = "把改动大小从拍脑袋变成一个可复算的数字，是这套流程能积累判断的前提。" * 10
work.joinpath("e_orig.md").write_text(base, encoding="utf-8")
work.joinpath("e_rev.md").write_text(base.replace("拍脑袋", "拍脑瓜", 1), encoding="utf-8")
EOF
check "one-char-edit-registers" "$WORK/e_orig.md" "$WORK/e_rev.md" 1 3

: > "$WORK/f_empty.md"
check "empty-vs-nonempty" "$WORK/f_empty.md" "$WORK/b_orig.md" 100 100

if python3 -c "import rapidfuzz" >/dev/null 2>&1; then
  fast="$(score "$WORK/a_orig.md" "$WORK/a_rev.md")" || fast="err"
  slow="$(DRIFT_FORCE_FALLBACK=1 python3 "$DRIFT" "$WORK/a_orig.md" "$WORK/a_rev.md" 2>/dev/null)" || slow="err"
  if [[ "$fast" != "err" && "$fast" == "$slow" ]]; then
    echo "  ok   backend-parity  rapidfuzz=$fast python=$slow"; pass=$((pass+1))
  else
    echo "  FAIL backend-parity  rapidfuzz=$fast python=$slow"; fail=$((fail+1))
  fi
else
  echo "  skip backend-parity  (rapidfuzz 未装，纯 Python 路径已被以上用例覆盖)"
fi

echo "=== $pass passed, $fail failed ==="
[[ $fail -eq 0 ]]
