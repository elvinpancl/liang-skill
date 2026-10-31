#!/usr/bin/env bash
# liang-promo-jianying 自测：合成素材 → 打码切片 → 切烘焙段 → 生成草稿 → 回读校验 → 篡改后校验必须失败。
# 不碰剪映、不碰真实草稿库。需要 ffmpeg（带 lavfi）和装了 pyjianyingdraft==0.3.1、pillow 的 Python。
# 用法：PYTHON=<venv>/bin/python bash selftest.sh [工作目录]
set -euo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
WORK="${1:-$(mktemp -d)}"
pass=0; fail=0
ok()  { echo "  通过  $1"; pass=$((pass+1)); }
bad() { echo "  失败  $1"; fail=$((fail+1)); }
cd "$S"

echo "工作目录：$WORK"
"$PY" -B -c "import pyJianYingDraft, PIL" 2>/dev/null || { echo "缺依赖：pyjianyingdraft==0.3.1、pillow"; exit 2; }

echo "1. 换算公式"
"$PY" -B - <<'PY' && ok "矩形→缩放位移，角点和中心投影误差 < 1e-9（含 k≠1）" || bad "换算公式"
import jy_camera
for canvas, source in [((1920,1080),(1920,1056)), ((1920,1080),(1280,720)), ((1080,1920),(1080,1920))]:
    c = jy_camera.Canvas(canvas, source)
    for rect in [[0,0,source[0],source[0]*canvas[1]/canvas[0]], [100,50,640,640*canvas[1]/canvas[0]]]:
        assert c.check_rect(rect) < 1e-9, (canvas, source, rect, c.check_rect(rect))
c = jy_camera.Canvas((1920,1080),(1920,1056))
s, tx, ty = c.camera_for_rect([1040,560,880,495])
assert abs(s-24/11) < 1e-12 and abs(tx+13/11) < 1e-12 and abs(ty-559/495) < 1e-12
PY

echo "2. 合成素材与计划"
"$PY" -B make_fixture.py "$WORK" >/dev/null && ok "合成素材" || { bad "合成素材"; exit 1; }

echo "3. 打码切片"
"$PY" -B sanitize_clips.py "$WORK/clips.json" >/dev/null && ok "sanitize_clips" || bad "sanitize_clips"
"$PY" -B - "$WORK" <<'PY' && ok "定格帧号与可用帧数" || bad "定格帧号与可用帧数"
import json, sys
m = {c["id"]: c for c in json.load(open(sys.argv[1] + "/素材/sanitize_manifest.json"))["clips"]}
r = m["R1"]
assert (r["source_in_frames"], r["story_frames"], r["story_last_frame_in_output"], r["frames"]) == (15, 60, 74, 90), r
assert r["rendered_mask_count"] == 1
PY

"$PY" -B mask_sheet.py "$WORK/素材/sanitize_manifest.json" --out "$WORK/打码抽检.jpg" >/dev/null && [ -s "$WORK/打码抽检.jpg" ] \
    && ok "打码抽检拼图" || bad "打码抽检拼图"

echo "4. 切烘焙段"
"$PY" -B cut_segments.py --plate "$WORK/源/底片.mp4" --seg B1_片头:0:30 --seg B2_片尾:30:60 \
    --out-dir "$WORK/素材" --total 60 --surrogate >/dev/null && ok "cut_segments" || bad "cut_segments"

echo "5. 生成草稿"
"$PY" -B build_draft.py "$WORK/draft_plan.json" --allow-surrogate >/dev/null && ok "build_draft" || bad "build_draft"
D="$WORK/staging/liang自测"
"$PY" -B build_draft.py "$WORK/draft_plan.json" >/dev/null 2>&1 && bad "替身素材没加 --allow-surrogate 也生成了" || ok "替身素材默认拒绝"

echo "6. 回读校验"
"$PY" -B verify_draft.py "$D" >/dev/null && ok "verify_draft 通过" || bad "verify_draft"
"$PY" -B - "$D" <<'PY' && ok "定格段、画中画边框、底衬都生成了" || bad "结构计数"
import json, sys
m = json.load(open(sys.argv[1] + "/build_manifest.json"))
r1 = next(s for s in m["shots"] if s["id"] == "R1")
assert [p["kind"] for p in r1["segments"]] == ["video", "freeze"], r1["segments"]
assert m["pip"][0]["border_segment_id"] and m["scrims"] and len(m["transitions"]) == 1
assert m["surrogate"] is True
PY

echo "7. 篡改后必须报错"
T="$WORK/篡改"; rm -rf "$T"; cp -R "$D" "$T"
"$PY" -B - "$T" <<'PY'
import json, sys
p = sys.argv[1] + "/draft_content.json"
d = json.load(open(p))
for t in d["tracks"]:
    if t["name"] == "文字-说明":
        t["segments"][0]["target_timerange"]["start"] += 200000
json.dump(d, open(p, "w"), ensure_ascii=False)
PY
"$PY" -B verify_draft.py "$T" >/dev/null 2>&1 && bad "说明时间被改了却没报错" || ok "说明时间被改能查出来"

echo "8. 布局预览"
"$PY" -B preview_layout.py "$D" --out "$WORK/布局预览" >/dev/null && [ -f "$WORK/布局预览/总览.jpg" ] \
    && ok "preview_layout 出图" || bad "preview_layout"

echo "9. 安装前检查"
FAKE="$WORK/假草稿库"; mkdir -p "$FAKE/liang自测"; echo '{"all_draft_store":[]}' > "$FAKE/root_meta_info.json"
out="$("$PY" -B jy_install.py --staging "$D" --draft-root "$FAKE" --root-meta "$FAKE/root_meta_info.json" --check 2>&1 || true)"
echo "$out" | grep -q "草稿名已存在" && ok "同名草稿拒绝安装" || bad "同名检查"
echo "$out" | grep -q "替身素材" && ok "替身草稿拒绝安装" || bad "替身检查"

echo
echo "通过 $pass 项，失败 $fail 项"
[ "$fail" -eq 0 ]
