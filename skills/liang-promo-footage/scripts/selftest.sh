#!/usr/bin/env bash
# liang-promo-footage 脚本自测：新增文字去重、打码扫描、抽帧。
# 用法：bash selftest.sh        没有 ffmpeg 时跳过抽帧测试；文字识别靠真实素材回归，不在这里测。

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

# 1. novel_lines.py：三段原片都有的菜单要被认成界面文字，重复行只出现一次
mkdir -p "$TMP/ocr"
for clip in 甲 乙 丙; do
  cat > "$TMP/ocr/$clip.txt" <<EOF
== ${clip}片段_t0000.5.jpg
首页 | 设置 | 欢迎使用
标题${clip}
== ${clip}片段_t0007.0.jpg
首页 | 设置
标题${clip}
新内容${clip}
EOF
done
python3 -I "$DIR/novel_lines.py" "$TMP/ocr" > "$TMP/novel.txt"
check "菜单被认成界面文字" 'grep -q "^# 界面固定文字（已去掉）：.*首页" "$TMP/novel.txt"'
check "正文里不再出现菜单" '! grep -v "^#" "$TMP/novel.txt" | grep -q "设置"'
check "新内容保留" 'grep -q "新内容乙" "$TMP/novel.txt"'
check "重复行只出现一次" '[ "$(grep -c "标题甲" "$TMP/novel.txt")" = 1 ]'

# 2. scan_sensitive.py：各类打码项都能扫出来，输出不泄露完整值
cat > "$TMP/stills.txt" <<'EOF'
== 01_凭据.jpg
凭据引用 | sk-TESTONLY1234567890abcd
联系人 | 13800000000 | demo.user@example.com
== 02_路径.jpg
Users > demo >Documents> 资料
== 03_干净.jpg
回答 | 进水一般不在免费保修范围
EOF
python3 -I "$DIR/scan_sensitive.py" "$TMP/stills.txt" --out "$TMP/mask.md" > "$TMP/scan.txt"
check "扫出密钥" 'grep -q "API 密钥：01_凭据" "$TMP/mask.md"'
check "扫出手机号" 'grep -q "手机号：01_凭据" "$TMP/mask.md"'
check "扫出邮箱" 'grep -q "邮箱：01_凭据" "$TMP/mask.md"'
check "扫出面包屑路径" 'grep -q "本机用户路径：02_路径" "$TMP/mask.md"'
check "干净的图不被标" '! grep -q "03_干净" "$TMP/mask.md"'
check "不泄露完整密钥" '! grep -q "TESTONLY12" "$TMP/mask.md" "$TMP/scan.txt"'
check "不泄露完整邮箱" '! grep -q "demo.user@example.com" "$TMP/mask.md" "$TMP/scan.txt"'

# 3. extract_frames.py：合成一段红 8 秒、蓝 8 秒的视频，应在 0.5、9.0、15.7 秒各取一帧
if command -v ffmpeg >/dev/null 2>&1; then
  mkdir -p "$TMP/src/演示"
  ffmpeg -hide_banner -loglevel error -nostdin \
    -f lavfi -i color=c=red:s=320x240:d=8 -f lavfi -i color=c=blue:s=320x240:d=8 \
    -filter_complex "[0:v][1:v]concat=n=2:v=1[v]" -map "[v]" -pix_fmt yuv420p \
    "$TMP/src/演示/双色.mp4" < /dev/null
  python3 -I "$DIR/extract_frames.py" "$TMP/src/演示" --out "$TMP/frames" > /dev/null
  check "写出索引" '[ -f "$TMP/frames/index.json" ]'
  check "取到变化点后的帧" '[ -f "$TMP/frames/演示/双色_t0009.0.jpg" ]'
  check "首尾帧都在" '[ -f "$TMP/frames/演示/双色_t0000.5.jpg" ] && [ -f "$TMP/frames/演示/双色_t0015.7.jpg" ]'
  check "一共 3 帧" '[ "$(ls "$TMP/frames/演示" | wc -l | tr -d " ")" = 3 ]'
  python3 -I "$DIR/extract_frames.py" "$TMP/src/演示" --list > "$TMP/list.txt"
  check "盘点读出分辨率" 'grep -q "320×240" "$TMP/list.txt"'
else
  echo "skip: 没有 ffmpeg，跳过抽帧测试"
fi

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
