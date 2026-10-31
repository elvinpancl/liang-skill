#!/usr/bin/env bash
# liang-promo-beat 自测：合成节拍音轨与硬切视频 → 逐帧分析 → 剪接 → 时间表 → 卡点回测 → 生成视频筛查 → 组件库构建。
# 需要 ffmpeg（带 lavfi、libmp3lame）、node，以及装了 librosa numpy scipy soundfile matplotlib pillow 的 Python。
# 用法：PYTHON=<venv>/bin/python bash selftest.sh [工作目录]
set -euo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
W="${1:-$(mktemp -d)}"
FF="${FFMPEG_BIN:-ffmpeg}"
pass=0; fail=0
ok()  { echo "  通过  $1"; pass=$((pass+1)); }
bad() { echo "  失败  $1"; fail=$((fail+1)); }
mkdir -p "$W"
echo "工作目录：$W"
"$PY" -B -c "import librosa, numpy, scipy, soundfile, matplotlib, PIL" 2>/dev/null || { echo "缺 Python 依赖"; exit 2; }

echo "1. 合成 120 BPM 节拍音轨（16 秒：底鼓在每拍，军鼓在 2、4 拍，镲在反拍）"
"$PY" -B - "$W/click.wav" <<'PY'
import sys, numpy as np, soundfile as sf
sr, bpm, dur = 44100, 120, 16.0
t = np.arange(int(sr*dur))/sr
y = np.zeros_like(t)
beat = 60/bpm
def hit(at, freq, decay, amp, noise=False):
    i = int(at*sr); n = int(.25*sr); tt = np.arange(n)/sr
    env = amp*np.exp(-tt*decay)
    sig = np.random.default_rng(int(at*1000)).standard_normal(n) if noise else np.sin(2*np.pi*freq*tt*(1-tt*2))
    y[i:i+n] += (env*sig)[:len(y)-i]
for k in range(int(dur/beat)):
    hit(k*beat, 60, 18, .9)
    if k % 2: hit(k*beat, 200, 25, .35, noise=True)
    hit(k*beat+beat/2, 0, 60, .12, noise=True)
sf.write(sys.argv[1], np.stack([y, y], 1)*.6, sr)
PY
[ -s "$W/click.wav" ] && ok "音轨已合成" || bad "音轨合成"

echo "2. 逐帧分析"
"$PY" -B "$S/analyze_frames.py" "$W/click.wav" "$W/分析" >/dev/null 2>&1 && ok "analyze_frames" || bad "analyze_frames"
"$PY" -B - "$W/分析/accents.json" <<'PY' && ok "BPM≈120、残差≤15 ms、480 帧、有三级重音" || bad "分析结果"
import json, sys
d = json.load(open(sys.argv[1]))
g = d["grid"]
assert abs(g["bpm"] - 120) < .5, g["bpm"]
assert g["residual_ms_max"] <= 15, g["residual_ms_max"]
assert d["audio"]["frames"] == 480, d["audio"]["frames"]
assert {a["level"] for a in d["accents"]} >= {"heavy"}, "没有 heavy"
PY

echo "3. 按小节剪接"
mkdir -p "$W/剪辑"
cat > "$W/剪辑/方案.json" <<'JSON'
{"src": "../click.wav", "grid_file": "../分析/accents.json", "output": "bgm.mp3", "crossfade_ms": 50, "headroom_db": 1.0,
 "segments": [{"start": 0, "end": 6, "label": "前段"}, {"start": 10, "end": "EOF", "label": "后段"}]}
JSON
(cd "$W/剪辑" && "$PY" -B "$S/cut_music.py" 方案.json >/dev/null 2>&1) && ok "cut_music" || bad "cut_music"
"$PY" -B - "$W/剪辑/splice_report.json" <<'PY' && ok "1 个接口、落在小节第一拍、时长约 12 秒" || bad "剪接报告"
import json, sys
r = json.load(open(sys.argv[1]))
assert len(r["interfaces"]) == 1
assert 11 < r["output"]["duration_sec"] < 13, r["output"]["duration_sec"]
PY

echo "4. 时间表"
"$PY" -B "$S/make_timing.py" "$W/分析/accents.json" "$W/timing.json" >/dev/null && ok "make_timing" || bad "make_timing"

echo "5. 卡点回测（合成视频在第 30、60、95 帧硬切）"
"$FF" -v error -y -f lavfi -i "color=c=0x202020:s=480x270:r=30:d=1" -f lavfi -i "color=c=0xe0e0e0:s=480x270:r=30:d=1" \
  -f lavfi -i "color=c=0x3060c0:s=480x270:r=30:d=1.1666667" -f lavfi -i "color=c=0xf0e070:s=480x270:r=30:d=0.8333333" \
  -filter_complex "[0][1][2][3]concat=n=4:v=1:a=0,format=yuv420p" -frames:v 120 "$W/硬切.mp4"
cat > "$W/anchors.json" <<'JSON'
{"sections": [["F1", 0, 120]],
 "anchors": [{"frame": 30, "kind": "S", "desc": "切 1"}, {"frame": 60, "kind": "S", "desc": "切 2"},
             {"frame": 95, "kind": "S", "desc": "切 3"}, {"frame": 80, "kind": "R", "desc": "人工看"}]}
JSON
"$PY" -B "$S/beat_check.py" "$W/硬切.mp4" --anchors "$W/anchors.json" --out-dir "$W/回测" --frames 120 >/dev/null \
  && ok "3 个切点都在 ±1 帧内" || bad "卡点回测"
cat > "$W/anchors_bad.json" <<'JSON'
{"anchors": [{"frame": 30, "kind": "S", "desc": "切 1"}, {"frame": 45, "kind": "S", "desc": "这里没有切"}]}
JSON
"$PY" -B "$S/beat_check.py" "$W/硬切.mp4" --anchors "$W/anchors_bad.json" --out-dir "$W/回测_反例" >/dev/null 2>&1 \
  && bad "没有切点的锚点没被报出" || ok "没有切点的锚点会报失败"

echo "6. 生成视频筛查"
"$PY" -B "$S/screen_generated.py" "$W/硬切.mp4" --out-dir "$W/筛查" --segments 2:28,63:92 >/dev/null && ok "切点检出、取段在镜头内" || bad "筛查"
"$PY" -B - "$W/筛查/生成视频筛查.json" <<'PY' && ok "检出的切点是 [30, 60, 95]" || bad "切点检出"
import json, sys
assert json.load(open(sys.argv[1]))["cuts"] == [30, 60, 95]
PY
"$PY" -B "$S/screen_generated.py" "$W/硬切.mp4" --out-dir "$W/筛查_反例" --segments 25:40 >/dev/null 2>&1 \
  && bad "跨镜头取段没被报出" || ok "跨镜头取段会报出"
"$FF" -v error -y -f lavfi -i "color=c=0x3060c0:s=480x270:r=30:d=1" -f lavfi -i "color=c=0xc06030:s=480x270:r=30:d=1" \
  -filter_complex "[0][1]concat=n=2:v=1:a=0,format=yuv420p" -frames:v 60 "$W/换色.mp4"
"$PY" -B "$S/screen_generated.py" "$W/换色.mp4" --out-dir "$W/筛查_换色" >/dev/null
"$PY" -B - "$W/筛查_换色/生成视频筛查.json" <<'PY' && ok "只换色相的切换列为疑似切点" || bad "疑似切点"
import json, sys
d = json.load(open(sys.argv[1]))
assert d["cuts"] == [] and d["maybe_cuts"] == [30], (d["cuts"], d["maybe_cuts"])
PY

echo "7. 组件库构建"
P="$W/工程"; mkdir -p "$P/src" "$P/assets/brand"
cat > "$P/src/01-demo.html" <<'HTML'
<template id="demo-template"><div id="demo-stage" data-composition-id="demo" data-duration="2" data-width="1920" data-height="1080">
<style>/* FX_CSS */</style><div id="slot"></div>
<script>/* FX_JS */
window.__timelines=window.__timelines||{};
const tl=gsap.timeline({paused:true});
ZRFX.textSlam(tl,{container:document.getElementById('slot'),durationF:60,fps:30,text:'测试',peakF:10});
window.__timelines['demo']=tl;
</script></div></template>
HTML
"$FF" -v error -y -f lavfi -i "color=c=0x5ad1ff:s=780x396" -frames:v 1 "$W/logo_2x.png"
B="$W/品牌"; mkdir -p "$B/logo"; cp "$S/../../liang-promo-jianying/assets/brand.example.json" "$B/brand.json"
cp "$W/logo_2x.png" "$B/logo/logo_2x.png"
node "$S/build-frames.mjs" --project "$P" --brand "$B/brand.json" --accents "$W/分析/accents.json" >/dev/null && ok "build-frames" || bad "build-frames"
node -e "
const fs=require('fs');const h=fs.readFileSync('$P/compositions/frames/01-demo.html','utf8');
const js=h.match(/<script>([\s\S]*?)<\/script>/)[1];
if(!/window\.FX_BRAND=/.test(js)||!/brandHeavyFrames/.test(js))process.exit(1);
if(!/#5ad1ff/.test(js)||/font-family:LTH/.test(h))process.exit(2);
new Function(js.replace(/^[\s\S]*?window\.FX_BRAND=/,'window.FX_BRAND='));" && ok "注入品牌配置和重拍帧号，脚本语法正确，没有写死的品牌" || bad "构建产物"
[ -f "$P/assets/brand/logo_2x.png" ] && ok "logo 已复制进工程" || bad "logo 复制"
node "$S/build-frames.mjs" --project "$P" --brand "$B/brand.json" --accents "$W/分析/accents.json" --plate >/dev/null \
  && grep -q 'data-jy-plate="true"' "$P/compositions/frames/01-demo.html" && grep -q "zr-callout" "$P/compositions/frames/01-demo.html" \
  && ok "底片模式带上了剪映底片样式" || bad "底片模式"

echo
echo "通过 $pass 项，失败 $fail 项"
[ "$fail" -eq 0 ]
