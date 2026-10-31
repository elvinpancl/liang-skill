#!/usr/bin/env bash
# 剪映实机冒烟：用合成素材按真实品牌包生成一份小草稿，装进剪映，人在剪映里打开看一遍。
# 换电脑、剪映升级、品牌包改了样式之后先跑它，再生成正式草稿。
# 用法：PYTHON=<venv>/bin/python bash smoke.sh <品牌包 brand.json> <草稿名> [--install] [--draft-root DIR] [--font-mode system]
# 不加 --install 只生成和校验，不碰剪映。安装前要完全退出剪映（Cmd+Q）。
set -euo pipefail
S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
BRAND="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; NAME="$2"; shift 2
INSTALL=0; ROOT_ARGS=(); FONT=system
while [ $# -gt 0 ]; do
  case "$1" in
    --install) INSTALL=1; shift;;
    --draft-root) ROOT_ARGS=(--draft-root "$2"); shift 2;;
    --font-mode) FONT="$2"; shift 2;;
    *) echo "未知参数：$1"; exit 2;;
  esac
done
WORK="${SMOKE_DIR:-$PWD/冒烟_$NAME}"
cd "$S"
"$PY" -B make_fixture.py "$WORK" --brand "$BRAND" --font-mode "$FONT" --name "$NAME"
"$PY" -B sanitize_clips.py "$WORK/clips.json"
"$PY" -B cut_segments.py --plate "$WORK/源/底片.mp4" --seg B1_片头:0:30 --seg B2_片尾:30:60 --out-dir "$WORK/素材" --total 60
"$PY" -B build_draft.py "$WORK/draft_plan.json"
"$PY" -B verify_draft.py "$WORK/staging/$NAME"
if [ "$INSTALL" = 1 ]; then
  "$PY" -B jy_install.py --staging "$WORK/staging/$NAME" "${ROOT_ARGS[@]}"
  cat <<TXT

在剪映里打开「$NAME」，逐项看：
1. 0–1 秒：烘焙段播放正常，1 秒处有「推近」转场。
2. 1–4 秒：录屏先全屏、再推近右下区域、2.3 秒有一次轻冲击；左上角有章节；左上那条白块被打码。
3. 1.3–2.7 秒：下方说明，品牌色胶囊底、6 帧弹入；画面下方有渐暗底衬。2.7–4 秒说明换到上方。
4. 3–5 秒：画中画带金色边框，3 秒放大入场，3.5 秒有一次节拍弹跳。
5. 说明和章节的字体是品牌包里的字体，不是剪映默认字体。
6. 全程有 440 Hz 正弦音。
TXT
fi
