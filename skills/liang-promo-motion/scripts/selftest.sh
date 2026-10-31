#!/usr/bin/env bash
# liang-promo-motion 自测：示例品牌包 + 模板 → 节奏检查 → 构建单文件 → 样帧 → 导出 MP4 并验收 → 导出透明 MOV 并验收。
# 需要 node、ffmpeg（带 libx264、prores_ks）、Chrome，以及能找到的 Playwright（VIDEO_NODE_MODULES）。
# 用法：bash selftest.sh [工作目录]
set -euo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
A="$S/../assets"
W="${1:-$(mktemp -d)}"
FF="${FFMPEG_BIN:-ffmpeg}"
pass=0; fail=0
ok()  { echo "  通过  $1"; pass=$((pass+1)); }
bad() { echo "  失败  $1"; fail=$((fail+1)); }
echo "工作目录：$W"
mkdir -p "$W/brand/logo" "$W/src"
cp "$A/example-brand/brand.json" "$A/example-brand/brand.css" "$W/brand/"
"$FF" -v error -y -f lavfi -i "color=c=0x5ad1ff:s=780x396,drawbox=x=60:y=60:w=260:h=276:color=0x04121a:t=fill" -frames:v 1 "$W/brand/logo/logo_2x.png"
"$FF" -v error -y -i "$W/brand/logo/logo_2x.png" -vf scale=390:198 "$W/brand/logo/logo.png"
cp "$A/template.src.html" "$W/src/index.src.html"

echo "1. 节奏检查"
node "$S/cue_lint.mjs" "$W/src/index.src.html" >/dev/null && ok "模板时间表通过" || bad "模板时间表"
sed "s/{id:'c2', t:2.6,/{id:'c2', t:1.2,/" "$W/src/index.src.html" > "$W/src/太快.src.html"
node "$S/cue_lint.mjs" "$W/src/太快.src.html" >/dev/null 2>&1 && bad "1.2 秒就切没被拦下" || ok "信息点停不到 2 秒会被拦下"
sed "s/{id:'c2', t:2.6, text:'一句话定位', done:4.8}/{id:'c2', t:2.6, text:'一句话定位', done:5.2}/" "$W/src/index.src.html" > "$W/src/没放完.src.html"
node "$S/cue_lint.mjs" "$W/src/没放完.src.html" >/dev/null 2>&1 && bad "动作没放完就切没被拦下" || ok "动作完成后停不到 0.7 秒会被拦下"
rm "$W/src/太快.src.html" "$W/src/没放完.src.html"

echo "2. 构建单文件"
node "$S/build.mjs" "$W/src/index.src.html" --brand "$W/brand/brand.json" --out "$W/片头.html" \
  --srt "$W/片头_旁白时间轴.srt" --sfx "$W/音效卡点.md" --expect-cues 3 >/dev/null && ok "build" || { bad "build"; exit 1; }
[ "$(grep -c -- '-->' "$W/片头_旁白时间轴.srt")" = 3 ] && ok "SRT 3 条" || bad "SRT 条数"
[ -s "$W/音效卡点.md" ] && ok "音效卡点表" || bad "音效卡点表"
grep -q 'url("fonts/' "$W/片头.html" && bad "字体没内嵌" || ok "字体已内嵌"
grep -q '/\*BRAND_CSS\*/\|brand:logo' "$W/片头.html" && bad "品牌标记没替换" || ok "品牌样式和 logo 已注入"
if [ -f "$W/src/fonts/Brand-Bold.subset.ttf" ]; then ok "按文案裁出字体子集"; else echo "  跳过  本机没有示例字体，未裁子集"; fi

echo "3. 样帧"
node "$S/export.mjs" "$W/片头.html" --samples --out-dir "$W/样帧" >/dev/null && ok "样帧" || bad "样帧"
[ "$(ls "$W/样帧"/t*.jpg | wc -l | tr -d ' ')" = 10 ] && ok "默认取 10 个时刻" || bad "样帧数量"

echo "4. 导出 MP4 并验收"
node "$S/export.mjs" "$W/片头.html" --render --out "$W/片头.mp4" --verify-samples "$W/样帧" --verify-out "$W/片头_验收.json" >/dev/null \
  && ok "MP4 导出，解码、帧数、bt709、样帧色差全部通过" || bad "MP4 导出或验收"

echo "5. 导出透明 MOV 并验收"
node "$S/export.mjs" "$W/片头.html" --render --alpha --out "$W/片头_透明.mov" --verify-samples "$W/样帧" --verify-out "$W/透明_验收.json" >/dev/null \
  && ok "ProRes 4444 带透明通道" || bad "透明导出或验收"
a=$("$FF" -v error -i "$W/片头_透明.mov" -vf "select=eq(n\,120),crop=1:1:0:0,format=rgba" -frames:v 1 -f rawvideo - | od -An -tu1 | awk '{print $4}')
[ "$a" = 0 ] && ok "背景确实透明（角点 alpha=0）" || bad "背景不透明（角点 alpha=$a）"

echo "6. 外置盘定位"
node -e "import('$S/lib.mjs').then(m=>{try{m.mediaDir('00000000-0000-0000-0000-000000000000','x');process.exit(1)}catch(e){process.exit(/未挂载/.test(e.message)?0:1)}})" \
  && ok "盘不在时报错停下，不改存本机" || bad "外置盘定位"

echo
echo "通过 $pass 项，失败 $fail 项"
[ "$fail" -eq 0 ]
