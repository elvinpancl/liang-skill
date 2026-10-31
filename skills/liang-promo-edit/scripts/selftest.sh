#!/usr/bin/env bash
# liang-promo-edit 脚本自测。用合成的录屏验证索引、粗剪、排时、开头渲染、发布前检查、复盘和逆向剪辑表。
# 用法：bash selftest.sh
# 没有 ffmpeg 时只跑纯文本的几项；不是 macOS 时跳过文字识别相关的几项。

set -uo pipefail

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

near() { python3 -I -c "import sys; sys.exit(0 if abs(float(sys.argv[1]) - float(sys.argv[2])) <= float(sys.argv[3]) else 1)" "$1" "$2" "$3"; }
dur() { python3 -I -c "
import sys; sys.path.insert(0, sys.argv[1]); import _common as C
p = C.probe(sys.argv[2]); print(round(p['duration'], 2) if p else -1)" "$DIR" "$1"; }

# 1. retro_compare.py：沿用、改写、新写的判定
cat > "$TMP/ai.md" <<'EOF'
| 序号 | 原片 | 入点 | 出点 | 旁白 |
|---|---|---|---|---|
| 1 | a.mp4 | 0 | 2 | 先建资料库／谁能看这批资料／建库时就定好了 |
EOF
printf '共用开场第一句\n为你展示本篇\n先建资料库\n建库时就定好了吗都行\n这是完全不同的句子\n' > "$TMP/final.txt"
python3 -I "$DIR/retro_compare.py" --ai "$TMP/ai.md" --final "$TMP/final.txt" --skip-until 展示 --json "$TMP/retro.json" > /dev/null
check "复盘：跳过共用开场后剩 3 句" 'python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d[\"final_lines\"]==3 else 1)" "$TMP/retro.json"'
check "复盘：沿用 5 字、改写 10 字、新写 9 字" 'python3 -I -c "
import json,sys; s=json.load(open(sys.argv[1]))[\"share\"]
ok = abs(s[\"沿用\"]-5/24)<0.01 and abs(s[\"改写\"]-10/24)<0.01 and abs(s[\"新写\"]-9/24)<0.01
sys.exit(0 if ok else 1)" "$TMP/retro.json"'

# 2. 表格解析：单元格里转义的竖线
printf '| 原片 | 入点 | 出点 | 备注 |\n|---|---|---|---|\n| a.mp4 | 0:01.5 | 1:02 | 含 \\| 竖线 |\n' > "$TMP/t.md"
check "表格：转义竖线和时间解析" 'python3 -I -c "
import sys; sys.path.insert(0, sys.argv[1]); import _common as C
h, rows = C.pick_table(sys.argv[2], [\"原片\", \"入点\", \"出点\"])
ok = rows[0][\"备注\"] == \"含 | 竖线\" and C.parse_time(rows[0][\"入点\"]) == 1.5 and C.parse_time(rows[0][\"出点\"]) == 62
sys.exit(0 if ok else 1)" "$DIR" "$TMP/t.md"'

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "skip: 没有 ffmpeg，跳过视频相关测试"
  echo "pass=$pass fail=$fail"
  [ "$fail" -eq 0 ]
  exit
fi

FONT=/System/Library/Fonts/Supplemental/Arial.ttf
[ -f "$FONT" ] || FONT=/System/Library/Fonts/Helvetica.ttc
mkdir -p "$TMP/src"
# 合成一段 14 秒的录屏：0–3 秒静止首页；3–5 秒有动静的处理中；5–8 秒输入法候选栏和打字；8–14 秒结果页，带假密钥和邮箱
ffmpeg -hide_banner -loglevel error -nostdin \
  -f lavfi -i color=c=white:s=1280x704:d=14:r=30 -f lavfi -i color=c=0x3366cc:s=60x60:d=14:r=30 \
  -filter_complex "[0:v][1:v]overlay=x='100+120*(t-3)':y=300:enable='between(t,3,8)'[b];[b]\
drawtext=fontfile=$FONT:text='Home Welcome Page':x=80:y=80:fontsize=48:fontcolor=black:enable='lt(t,8)',\
drawtext=fontfile=$FONT:text='Processing your request':x=80:y=200:fontsize=44:fontcolor=black:enable='between(t,3,5)',\
drawtext=fontfile=$FONT:text='1.ab 2.cd 3.ef 4.gh':x=80:y=420:fontsize=44:fontcolor=black:enable='between(t,5,8)',\
drawtext=fontfile=$FONT:text='Result ready 10 files':x=80:y=200:fontsize=52:fontcolor=black:enable='gte(t,8)',\
drawtext=fontfile=$FONT:text='sk-TESTONLY1234567890abcd':x=80:y=500:fontsize=44:fontcolor=black:enable='gte(t,8)',\
drawtext=fontfile=$FONT:text='demo.user@example.com':x=80:y=580:fontsize=44:fontcolor=black:enable='gte(t,8)'[v]" \
  -map "[v]" -pix_fmt yuv420p "$TMP/src/demo.mp4" < /dev/null
check "合成录屏生成" '[ -f "$TMP/src/demo.mp4" ]'

# 3. 粗剪：时长、加速、放大备选、叠化和闪黑后的预览时长、打码
cat > "$TMP/script.md" <<'EOF'
| 序号 | 段落 | 身份 | 原片 | 入点 | 出点 | 速度 | 转场 | 放大 | 打码 | 旁白 | 音效 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 首页 | 甲 | demo.mp4 | 0 | 3 | 1 | 切 | 左上推 |  | 先看首页／这是一句很长很长的旁白用来测试超出画面 | 点击 |
| 2 | 打字 | 甲 | demo.mp4 | 5 | 8 | 2 | 叠化 |  |  |  | 键盘 |
| 3 | 结果 | 乙 | demo.mp4 | 8 | 14 | 1 | 闪黑 | 中心 | 0.03,0.66,0.94,0.24 | @3 结果出来了 | 唰 |
EOF
python3 -I "$DIR/build_roughcut.py" "$TMP/script.md" --src "$TMP/src" --out "$TMP/ep" > /dev/null
check "粗剪：第 1 段 3 秒" 'near "$(dur "$TMP/ep/粗剪/01_首页.mp4")" 3 0.1'
check "粗剪：第 2 段 2 倍速 1.5 秒" 'near "$(dur "$TMP/ep/粗剪/02_打字.mp4")" 1.5 0.1'
check "粗剪：第 3 段 6 秒" 'near "$(dur "$TMP/ep/粗剪/03_结果.mp4")" 6 0.1'
check "粗剪：预览片扣掉一次叠化共 10 秒" 'near "$(dur "$TMP/ep/粗剪预览.mp4")" 10 0.15'
check "粗剪：放大备选和原片同尺寸" 'python3 -I -c "
import sys; sys.path.insert(0, sys.argv[1]); import _common as C
a = C.probe(sys.argv[2]); b = C.probe(sys.argv[3])
sys.exit(0 if (a[\"width\"], a[\"height\"]) == (b[\"width\"], b[\"height\"]) == (1280, 704) else 1)" "$DIR" "$TMP/ep/粗剪/01_首页.mp4" "$TMP/ep/粗剪/放大备选/01_首页_放大.mp4"'
check "粗剪：索引记下预览起点" 'python3 -I -c "
import json,sys; s=json.load(open(sys.argv[1]))[\"shots\"]
sys.exit(0 if [x[\"preview_start\"] for x in s] == [0.0, 2.5, 4.0] else 1)" "$TMP/ep/制作过程/粗剪索引.json"'

# 4. 排时：超出画面报出来、长句报出来、锚点生效、退出码 2
python3 -I "$DIR/make_subtitles.py" --index "$TMP/ep/制作过程/粗剪索引.json" --script "$TMP/script.md" --out "$TMP/ep" --chapter "1、测试" > "$TMP/sub.txt"
code=$?
check "排时：有超出时退出码 2" '[ "$code" = 2 ]'
check "排时：报出超长句" 'grep -q "超过 14 字" "$TMP/sub.txt"'
srt_starts() { python3 -I -c "
import re,sys
for h,m,s,ms in re.findall(r'(\d\d):(\d\d):(\d\d),(\d\d\d) -->', open(sys.argv[1],encoding='utf-8').read()):
    print(int(h)*3600+int(m)*60+int(s)+int(ms)/1000)" "$1"; }
check "排时：SRT 3 句且时间递增" '[ "$(srt_starts "$TMP/ep/字幕.srt" | wc -l | tr -d " ")" = 3 ] && [ "$(srt_starts "$TMP/ep/字幕.srt")" = "$(srt_starts "$TMP/ep/字幕.srt" | sort -n)" ]'
check "排时：锚点让第 3 段在镜头开始后 3 秒开口（7.0 秒）" 'near "$(srt_starts "$TMP/ep/字幕.srt" | tail -1)" 7.0 0.01'
check "排时：包装清单标出身份切换" 'grep -q "切换：乙" "$TMP/ep/包装清单.md"'

# 5. 开头渲染：两张状态图，时长按旁白算
ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i color=c=navy:s=1280x720 -frames:v 1 \
  -vf "drawtext=fontfile=$FONT:text='Card One':x=100:y=100:fontsize=60:fontcolor=white" "$TMP/s1.png" < /dev/null
ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i color=c=navy:s=1280x720 -frames:v 1 \
  -vf "drawtext=fontfile=$FONT:text='Card Two':x=100:y=100:fontsize=60:fontcolor=white" "$TMP/s2.png" < /dev/null
printf '| 状态图 | 旁白 | 最短停留 |\n|---|---|---|\n| s1.png | 第一张卡 | |\n| s2.png | 第二张卡亮起 | |\n' > "$TMP/cues.md"
python3 -I "$DIR/render_slides.py" "$TMP/cues.md" --out "$TMP/open/开头.mp4" > /dev/null
check "开头：时长约 2.75 秒（句间不留空档，最后一张停 0.5 秒）" 'near "$(dur "$TMP/open/开头.mp4")" 2.75 0.15'
check "开头：出了 SRT 和排时表" '[ -f "$TMP/open/开头.srt" ] && [ -f "$TMP/open/制作过程/开头_排时.md" ]'

# 6. 从放映录屏取状态图：三张卡轮流亮、放两遍，不去重 6 个状态，去重后 3 个，状态表能直接渲染
boxes=""
for i in 0 1 2; do
  x=$((80 + i * 300))
  boxes="$boxes,drawbox=x=$x:y=300:w=220:h=140:color=0x404060:t=fill,drawbox=x=$x:y=300:w=220:h=140:color=0x9090d0:t=fill:enable='eq(mod(floor(t/2),3),$i)'"
done
ffmpeg -hide_banner -loglevel error -nostdin -f lavfi -i color=c=0x101830:s=1280x720:d=12:r=30 \
  -vf "null$boxes" -pix_fmt yuv420p "$TMP/show.mp4" < /dev/null
python3 -I "$DIR/render_slides.py" --from-video "$TMP/show.mp4" --states "$TMP/st_all" --no-ocr > /dev/null
python3 -I "$DIR/render_slides.py" --from-video "$TMP/show.mp4" --states "$TMP/st_one" --no-ocr --dedupe > /dev/null
check "取状态图：不去重 6 个" '[ "$(ls "$TMP/st_all" | grep -c png)" = 6 ]'
check "取状态图：去重后 3 个" '[ "$(ls "$TMP/st_one" | grep -c png)" = 3 ]'
check "取状态图：状态表能直接渲染" 'python3 -I "$DIR/render_slides.py" "$TMP/st_one/状态表.md" --out "$TMP/st_one/开头.mp4" > /dev/null && near "$(dur "$TMP/st_one/开头.mp4")" 3.9 0.2'

# 7. 校准记录里的默认值能读出来，读不到用后备值
check "校准默认值：字幕语速 4.7、未知参数用后备值" 'python3 -I -c "
import sys; sys.path.insert(0, sys.argv[1]); import _common as C
ok = C.calib_default(\"make_subtitles.py --rate\", 0) == 4.7 and C.calib_default(\"不存在的参数\", 9.9) == 9.9
sys.exit(0 if ok else 1)" "$DIR"'

if [ "$(uname)" != "Darwin" ]; then
  echo "skip: 不是 macOS，跳过文字识别相关测试"
  echo "pass=$pass fail=$fail"
  [ "$fail" -eq 0 ]
  exit
fi

# 8. 镜头索引：静止、等待、打字、要打码
python3 -I "$DIR/index_clips.py" "$TMP/src" --out "$TMP/idx" > /dev/null 2>&1
check "索引：写出总表" '[ -f "$TMP/idx/镜头索引.md" ]'
check "索引：认出等待、打字和要打码" 'python3 -I -c "
import json,sys
d=json.load(open(sys.argv[1]))
seg=d[\"segments\"]
ok = any(s[\"wait\"] for s in seg) and any(s[\"typing\"] for s in seg) and any(\"API 密钥\" in s[\"sensitive\"] and s[\"mask_boxes\"] for s in seg)
ok = ok and any(b-a >= 1.5 for a,b in d[\"static\"])
sys.exit(0 if ok else 1)" "$TMP/idx/src__demo.json"'

# 9. 发布前检查：原片扫出密钥和邮箱，打过码的片段扫不出来，报告不泄露完整值
python3 -I "$DIR/qa_export.py" "$TMP/src/demo.mp4" "$TMP/ep/粗剪/03_结果.mp4" --out "$TMP/qa.md" > /dev/null 2>&1
check "检查：原片扫出密钥" 'awk "/## demo.mp4/,/## 03_结果.mp4/" "$TMP/qa.md" | grep -q "API 密钥"'
check "检查：原片扫出邮箱" 'awk "/## demo.mp4/,/## 03_结果.mp4/" "$TMP/qa.md" | grep -q "邮箱"'
check "检查：打码后的片段没有必须处理" 'awk "/## 03_结果.mp4/,0" "$TMP/qa.md" | grep -q "没有扫出必须打码的画面"'
check "检查：报告不泄露完整密钥和邮箱" '! grep -q "TESTONLY12" "$TMP/qa.md" && ! grep -q "demo.user@example.com" "$TMP/qa.md"'
check "检查：认出输入法候选栏" 'grep -q "输入法候选栏" "$TMP/qa.md"'

# 10. 逆向剪辑表：预览片能对回原片，并落在台本区间里
python3 -I "$DIR/reverse_edl.py" "$TMP/ep/粗剪预览.mp4" --index "$TMP/idx" --script "$TMP/script.md" --work "$TMP/rev" --out "$TMP/rev.md" --json "$TMP/rev.json" > /dev/null 2>&1
check "逆向：多数画面对回原片，且落在台本区间里" 'python3 -I -c "
import json,sys; d=json.load(open(sys.argv[1]))
sys.exit(0 if d[\"matched\"] >= 0.6*d[\"analyzed\"] and (d[\"coverage\"] or 0) >= 0.8 else 1)" "$TMP/rev.json"'

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
