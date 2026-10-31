#!/usr/bin/env bash
# check_article.py 自测：干净稿通过，问题稿每类硬伤都报出来，「」里的原话不误报。
# 用法：bash check_article_test.sh

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0
fail=0

check() {
  if eval "$2"; then
    pass=$((pass + 1))
  else
    echo "FAIL: $1"
    fail=$((fail + 1))
  fi
}

mkdir -p "$TMP/配图"
printf 'x' > "$TMP/配图/01.jpg"

cat > "$TMP/good.md" <<'EOF'
# 从一个售后客服，看懂某平台的能力

很多企业的 AI 试点，都卡在同一个地方。

演示里，问它「你是谁」，它回答「我是本店的售后客服助手，状态：已启用」。

演示公司叫小B家电，接口地址写在 https://example.com/mcp 里。

![图片](配图/01.jpg)

对企业来说，资料里没有的不猜，这一下比答对一道题更值钱。
EOF

cat > "$TMP/bad.md" <<'EOF'
# 问题稿

## 小标题

结论：说白了，这个功能——很好用。

我觉得用AI做客服，你会喜欢“它”。

- 第一项

**重点**

界面上写着「状态：已启用」。

![图片](配图/不存在.jpg)
EOF

python3 -I "$DIR/check_article.py" "$TMP/good.md" --third-person --allow-term 小B家电 > "$TMP/good.txt" && good_code=0 || good_code=$?
check "干净稿退出码为 0" '[ "$good_code" = 0 ]'
check "干净稿硬伤为 0" 'grep -q "硬伤 0" "$TMP/good.txt"'
check "干净稿配图齐全" 'grep -q "配图 1，缺 0" "$TMP/good.txt"'

python3 -I "$DIR/check_article.py" "$TMP/bad.md" --third-person > "$TMP/bad.txt" && bad_code=0 || bad_code=$?
check "问题稿退出码为 1" '[ "$bad_code" = 1 ]'
for category in 冒号 破折号 双引号 套话 加粗 中英文缺空格 「」外的人称 小标题 列表 缺图; do
  check "报出$category" 'grep -q "^  $category " "$TMP/bad.txt"'
done
check "「」里的冒号不算" 'grep -q "^  冒号 1 处" "$TMP/bad.txt"'

python3 -I "$DIR/check_article.py" "$TMP/good.md" > "$TMP/plain.txt" && plain_code=0 || plain_code=$?
check "不加 --allow-term 时报出专名连写" '[ "$plain_code" = 1 ] && grep -q "中英文缺空格" "$TMP/plain.txt"'

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
