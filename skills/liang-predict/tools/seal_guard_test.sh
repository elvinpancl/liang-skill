#!/usr/bin/env bash
#
# seal_guard_test.sh — behavioural test for seal-guard.sh
#
# 用一张标准预测卡逐项验证放行 / 拦截边界：
#   A  Edit 改封存段内容                        -> 拦 (2)
#   B  以「## 复盘」为锚位追加「## 预测 v2」    -> 放 (0)
#   C  Edit 改 header 登记行                    -> 放 (0)
#   D  Edit 填复盘段占位行                      -> 放 (0)
#   E  Write 新建预测卡                         -> 放 (0)
#   F  predictions/ 路径（coc 的卡，井水不犯河水）-> 放 (0)
#   F2 非 bets 路径但内容里出现 bets/ 字样      -> 放 (0)（粗筛不误伤）
#   G  LIANG_SEAL_BYPASS=1 旁路 A 的改动        -> 放 (0)
#   H  Write 覆盖已有卡且封存段被改             -> 拦 (2)
#   I  Write 覆盖已有卡且封存段原样保留         -> 放 (0)
#   J  Edit 触到「## 预测」标题行本身           -> 拦 (2)
#   K  Edit 的 old_string 跨封存段边界          -> 拦 (2)
#   L  空 stdin                                 -> 放 (0)
#
# Run:  bash seal_guard_test.sh
# Exit: 0 all pass | 1 any fail
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="${1:-$HERE/seal-guard.sh}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
pass=0 fail=0

mkdir -p "$WORK/bets" "$WORK/predictions"
CARD="$WORK/bets/2026-07-05-测试卡.md"
cat > "$CARD" <<'EOF'
# 测试卡

- 稿子：drafts/x.md
- 立卡日：2026-07-05
- 状态：已预测
- 发布链接：
- 发布时间：
- 复盘到期：

## 预测（封存段：落笔即封，只许整段追加 v2，不许改动一字）

| 维度 | 分 | 一句理由 |
|---|---|---|
| 钩子力 | 4 | 首句反差把人拽住 |

综合分：3.8（评分卡 v0，子代理盲打）
概率分布：哑火 10% ｜ 常规 55% ｜ 出圈 30% ｜ 爆款 5%（加总 100）
赌档位：常规，中枢约基线 1.2 倍
一句话赌注：钩子力是胜负手
若高一档：低估了选题势能
若低一档：高估了钩子力

## 复盘

（等 /liang-retro 来写）
EOF
cp "$CARD" "$WORK/predictions/coc-card.md"

edit_json() {
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Edit","tool_input":{"file_path":sys.argv[1],"old_string":sys.argv[2],"new_string":sys.argv[3]}}))' "$1" "$2" "$3"
}
write_json() {
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":sys.argv[2]}}))' "$1" "$2"
}

check() {
  local name="$1" want="$2" json="$3" rc=0
  printf '%s' "$json" | bash "$GUARD" >/dev/null 2>&1 || rc=$?
  if [[ "$rc" == "$want" ]]; then
    echo "  ok   $name  rc=$rc"; pass=$((pass+1))
  else
    echo "  FAIL $name  rc=$rc want=$want"; fail=$((fail+1))
  fi
}

check "A-edit-sealed-line"   2 "$(edit_json "$CARD" "一句话赌注：钩子力是胜负手" "一句话赌注：改口了")"
check "B-append-v2-at-anchor" 0 "$(edit_json "$CARD" "## 复盘" "## 预测 v2

（新赌注整段追加）

## 复盘")"
check "C-header-edit"        0 "$(edit_json "$CARD" "- 状态：已预测" "- 状态：已发布")"
check "D-retro-fill"         0 "$(edit_json "$CARD" "（等 /liang-retro 来写）" "- 实际数据：3.2w 播放")"
check "E-write-new-card"     0 "$(write_json "$WORK/bets/new-card.md" "# 新卡

## 预测

综合分：3.0")"
check "F-coc-predictions-path" 0 "$(edit_json "$WORK/predictions/coc-card.md" "一句话赌注：钩子力是胜负手" "一句话赌注：改口了")"
check "F2-bets-mention-in-content" 0 "$(edit_json "$WORK/predictions/coc-card.md" "一句话赌注：钩子力是胜负手" "提到 bets/ 字样不该触发拦截")"

rc=0
printf '%s' "$(edit_json "$CARD" "一句话赌注：钩子力是胜负手" "一句话赌注：改口了")" \
  | LIANG_SEAL_BYPASS=1 bash "$GUARD" >/dev/null 2>&1 || rc=$?
if [[ "$rc" == "0" ]]; then
  echo "  ok   G-bypass-env  rc=$rc"; pass=$((pass+1))
else
  echo "  FAIL G-bypass-env  rc=$rc want=0"; fail=$((fail+1))
fi

tampered="$(python3 -c 'import sys; t=open(sys.argv[1],encoding="utf-8").read(); sys.stdout.write(t.replace("钩子力是胜负手","改口了"))' "$CARD")"
check "H-write-tampered-sealed" 2 "$(write_json "$CARD" "$tampered")"

kept="$(python3 -c 'import sys; t=open(sys.argv[1],encoding="utf-8").read(); sys.stdout.write(t.replace("（等 /liang-retro 来写）","- 实际数据：3.2w 播放"))' "$CARD")"
check "I-write-sealed-preserved" 0 "$(write_json "$CARD" "$kept")"

check "J-edit-sealed-heading" 2 "$(edit_json "$CARD" "## 预测（封存段：落笔即封，只许整段追加 v2，不许改动一字）" "## 预测 v1")"
check "K-edit-spanning-boundary" 2 "$(edit_json "$CARD" "若低一档：高估了钩子力

## 复盘" "若低一档：另一套说法

## 复盘")"

rc=0
printf '' | bash "$GUARD" >/dev/null 2>&1 || rc=$?
if [[ "$rc" == "0" ]]; then
  echo "  ok   L-empty-stdin  rc=$rc"; pass=$((pass+1))
else
  echo "  FAIL L-empty-stdin  rc=$rc want=0"; fail=$((fail+1))
fi

echo "=== $pass passed, $fail failed ==="
[[ $fail -eq 0 ]]
