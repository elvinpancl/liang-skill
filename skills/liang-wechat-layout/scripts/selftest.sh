#!/usr/bin/env bash
# render_wechat.py 自测：样例稿排出来的片段符合约定，坏片段和坏稿件都被拦下。
# 用法：bash selftest.sh

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
R() { python3 -I "$DIR/render_wechat.py" "$@"; }
TMP="$(mktemp -d)"
LIVE_PID=""
trap '[[ -n "$LIVE_PID" ]] && kill "$LIVE_PID" 2> /dev/null; rm -rf "$TMP"' EXIT
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

# 从预览页里取出被复制的片段，供后面逐项检查
fragment() {
  python3 -I -c '
import json, re, sys
page = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"<div id=\"wx\"[^>]*>\n(.*?)\n  </div>\n</div>\n<script>", page, re.S)
print(m.group(1))
' "$1"
}

R "$DIR/fixtures/样例稿.md" --out "$TMP" > "$TMP/log.txt"
OUT="$TMP/样例稿_公众号排版.html"
fragment "$OUT" > "$TMP/frag.html"
F="$TMP/frag.html"

check "样例稿排版成功、静态检查通过" "grep -q '静态检查：通过' '$TMP/log.txt'"
check "预览页按稿名命名" "test -f '$OUT'"
check "标题不进正文" "! grep -q '小店的账' '$F'"
check "标题写进预览页 title" "grep -q '<title>小店的账，越算越细</title>' '$OUT'"
check "小节按顺序编号 01 02 03" "grep -o '>0[1-9]</span>' '$F' | tr -d '\n' | grep -q '>01</span>>02</span>>03</span>'"
check "标题自带编号被去掉" "grep -q '>从一张手写单说起<' '$F' && grep -q '>备料不再靠感觉<' '$F' && grep -q '>账算细了，也有代价<' '$F'"
check "重点句转成橙色加粗" "test \$(grep -o 'font-weight:bold;color:#E28B08;' '$F' | wc -l) -eq 4"
check "没有残留 **" "! grep -q '\*\*' '$F'"
check "导语行高 1.5em，正文 2em" "grep -q '>县城里开了十年的面馆' '$F' && grep '县城里' '$F' | grep -q 'line-height:1.5em' && grep '青梧镇' '$F' | grep -q 'line-height:2em'"
check "找不到的本地图片出占位框" "grep -q '【此处插入图片】点单界面截图（01.png）' '$F' && ! grep -q 'src=\"配图' '$F'"
check "日志列出找不到的图片" "grep -q '找不到的图片 1 张' '$TMP/log.txt'"
check "https 图片直接出图" "grep -q '<img src=\"https://example.com/shop.jpg\"' '$F'"
check "HTML 特殊字符被转义" "grep -q 'A&amp;B' '$F' && grep -q '&lt;b&gt;不强推&lt;/b&gt;' '$F'"
check "列表转成带点的段落" "grep -q '>· 牛肉面按周均值备<' '$F'"
check "连续引用合成一块" "test \$(grep -c 'border-left:3px solid' '$F') -eq 1 && grep -q '宁可多备。」<br>「现在' '$F'"
check "片段不含 style 标签、class、id、script" "! grep -Eq '<style|<script| class=| id=' '$F'"
check "预览页带复制标题和复制正文两个按钮" "grep -q '① 复制标题' '$OUT' && grep -q '② 复制正文到公众号' '$OUT'"
check "预览页正文栏同公众号网页版，最宽 677px" "grep -qF '.page { max-width: 677px' '$OUT' && ! grep -q 'max-width: 390px' '$OUT'"
check "两侧用微信底灰，正文栏白底" "grep -qF 'body { margin: 0; background: #EDEDED' '$OUT' && grep -qF 'padding: 0 20px; background: #FFFFFF' '$OUT'"
check "日志列出图片占位" "grep -q '点单界面截图（配图/01.png）' '$TMP/log.txt'"

# 本地图片嵌入：稿件旁边的图转成 data URI，宽图缩到 1440，PNG 不转 JPEG
mkdir -p "$TMP/img/配图"
python3 -I -c '
import struct, sys, zlib
def png(path, w, h):
    raw = b"".join(b"\x00" + bytes([200, 80, 30]) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
png(sys.argv[1], 2000, 40)
' "$TMP/img/配图/宽图.png"
printf '# 嵌图\n\n## 一节\n\n正文。\n\n![宽图](配图/宽图.png)\n' > "$TMP/img/嵌图.md"
R "$TMP/img/嵌图.md" > "$TMP/img.log"
fragment "$TMP/img/嵌图_公众号排版.html" > "$TMP/img.html"
check "本地图片嵌进片段，不出占位框" "grep -q '<img src=\"data:image/' '$TMP/img.html' && ! grep -q '此处插入图片' '$TMP/img.html'"
check "日志报嵌入张数" "grep -q '嵌入图片 1 张' '$TMP/img.log' && grep -q '静态检查：通过' '$TMP/img.log'"
if command -v sips > /dev/null; then
  python3 -I -c '
import base64, re, sys
m = re.search(r"data:image/png;base64,([^\"]+)", open(sys.argv[1], encoding="utf-8").read())
open(sys.argv[2], "wb").write(base64.b64decode(m.group(1)) if m else b"")
' "$TMP/img.html" "$TMP/img/decoded.png"
  check "宽图缩到 1440，PNG 还是 PNG" "sips -g pixelWidth -g format '$TMP/img/decoded.png' | grep -q 'pixelWidth: 1440' && sips -g format '$TMP/img/decoded.png' | grep -q 'format: png'"
fi
check "预览页提示按系统写 Ctrl 或 Cmd，复制失败时留着选区" "grep -q 'const MOD = /Mac|iPhone|iPad/' '$TMP/img/嵌图_公众号排版.html' && grep -q '\${MOD}+V' '$TMP/img/嵌图_公众号排版.html' && grep -q 'if (ok) sel.removeAllRanges();' '$TMP/img/嵌图_公众号排版.html' && ! grep -q 'Cmd+' '$TMP/img/嵌图_公众号排版.html'"
R "$TMP/img/嵌图.md" --no-embed --out "$TMP/img/noembed.html" > /dev/null
fragment "$TMP/img/noembed.html" > "$TMP/noembed.html"
check "--no-embed 时出占位框" "grep -q '【此处插入图片】宽图（宽图.png）' '$TMP/noembed.html' && ! grep -q 'data:image/' '$TMP/noembed.html'"

# 正文里的数字不当编号去掉
printf '# 标题\n\n## 10 倍增长的背后\n\n## 3.5 倍的差距\n\n## 2026年的变化\n\n正文。\n' > "$TMP/nums.md"
R "$TMP/nums.md" --out "$TMP" > /dev/null
fragment "$TMP/nums_公众号排版.html" > "$TMP/nums.html"
check "「10 倍」「3.5 倍」「2026年」不被当成编号" "grep -q '>10 倍增长的背后<' '$TMP/nums.html' && grep -q '>3.5 倍的差距<' '$TMP/nums.html' && grep -q '>2026年的变化<' '$TMP/nums.html'"

# 纯文本稿：没有标题、没有空行，一行一段
printf '第一段。\n第二段。\n第三段。\n' > "$TMP/plain.txt"
R "$TMP/plain.txt" --out "$TMP" > "$TMP/plain.log"
fragment "$TMP/plain_公众号排版.html" > "$TMP/plain.html"
check "纯文本一行一段，没有小节时都按正文排" "test \$(grep -c 'line-height:2em;text-align:justify' '$TMP/plain.html') -eq 3"
check "没有重点标记时提示先挑重点" "grep -q '没有 \*\* 重点标记' '$TMP/plain.log'"

# 标记稿在「制作过程/」里时，预览页写到上一级、去掉「_标记稿」
mkdir -p "$TMP/proj/制作过程"
cp "$DIR/fixtures/样例稿.md" "$TMP/proj/制作过程/样例稿_标记稿.md"
R "$TMP/proj/制作过程/样例稿_标记稿.md" > /dev/null
check "标记稿的预览页写到上一级目录" "test -f '$TMP/proj/样例稿_公众号排版.html'"

# 换主题
printf '{"accent": "#C0392B"}\n' > "$TMP/brand.json"
R "$DIR/fixtures/样例稿.md" --theme "$TMP/brand.json" --out "$TMP/brand.html" > /dev/null
check "主题文件覆盖强调色，其余沿用默认" "grep -q 'color:#C0392B' '$TMP/brand.html' && grep -q '#196CF0' '$TMP/brand.html'"

# 卡片版式
R "$DIR/fixtures/样例稿.md" --theme card --out "$TMP/card.html" > "$TMP/card.log"
fragment "$TMP/card.html" > "$TMP/card_frag.html"
C="$TMP/card_frag.html"
check "卡片版式静态检查通过" "grep -q '静态检查：通过' '$TMP/card.log'"
check "卡片版式小节编号 01 02 03" "test \$(grep -o 'letter-spacing:2px;line-height:1.6;color:#6B4CF5;\">0[1-3]</span>' '$C' | wc -l) -eq 3"
check "小节标题在逗号处断两行，后一行用强调色" "grep -q '>账算细了，</span>' '$C' && grep -q 'color:#6B4CF5;\">也有代价</span>' '$C'"
check "正文前有标题卡，最后一个分句用强调色" "grep -q 'linear-gradient(#EFEBFD' '$C' && grep -q '小店的账，<br><span style=\"color:#6B4CF5;\">越算越细</span>' '$C'"
check "整段重点排成左侧色条的提示框" "test \$(grep -c 'border-left:3px solid #6B4CF5' '$C') -eq 2"
check "最后一段整段重点排成淡色收尾卡，强调色字" "grep -q 'background-color:#F3F1FE;border-radius:14px' '$C' && grep -q 'letter-spacing:1px;color:#6B4CF5;\">工具能把账算细' '$C' && grep -q '工具能把账算细，但留不留得住人，<br>还得看店里的人情味。' '$C'"
check "半句重点用强调色" "grep -q 'font-weight:bold;color:#6B4CF5;\">备料第一次可以按数字来' '$C'"
check "连续列表合进一个底色框" "grep '牛肉面按周均值备' '$C' | grep -q '时令浇头' && test \$(grep -o '▸' '$C' | wc -l) -eq 2"
check "正文 15px 左对齐，行高按正文字号算" "grep '青梧镇' '$C' | grep -q 'font-size:15px;line-height:1.85;text-align:left'"
printf '{"layout": "card", "accent": "#0A7F5A"}\n' > "$TMP/card_brand.json"
R "$DIR/fixtures/样例稿.md" --theme "$TMP/card_brand.json" --out "$TMP/card_brand.html" > /dev/null
check "主题只写 layout 时补齐卡片版式的默认值" "grep -q 'color:#0A7F5A' '$TMP/card_brand.html' && grep -q '#F3F1FE' '$TMP/card_brand.html' && ! grep -q '#6B4CF5' '$TMP/card_brand.html'"

# 实时预览：改稿后版本号变、页面跟着变；写到磁盘的预览页不带刷新脚本
mkdir -p "$TMP/live"
printf '# 实时\n\n## 一节\n\n第一版正文。\n' > "$TMP/live/live.md"
python3 -I "$DIR/render_wechat.py" "$TMP/live/live.md" --watch --port 0 > "$TMP/live.log" 2>&1 &
LIVE_PID=$!
get() { curl -s --noproxy '*' "$1" || true; }
url=""
for _ in $(seq 1 50); do
  url=$(grep -o 'http://127.0.0.1:[0-9]*/' "$TMP/live.log" | head -1 || true)
  [[ -n "$url" ]] && break
  sleep 0.1
done
v1=$(get "${url}__version")
check "实时预览起服务并给出地址" "[[ -n '$url' && -n '$v1' ]]"
check "实时预览页带自动刷新脚本" "get '$url' | grep -q '/__version'"
printf '# 实时\n\n## 一节\n\n第二版正文。\n' > "$TMP/live/live.md"
v2="$v1"
for _ in $(seq 1 50); do
  v2=$(get "${url}__version")
  [[ "$v2" != "$v1" ]] && break
  sleep 0.1
done
check "改稿后版本号变化" "[[ '$v2' != '$v1' ]]"
check "刷新后页面是新内容" "get '$url' | grep -q '第二版正文'"
check "磁盘上的预览页也更新，不带刷新脚本" "grep -q '第二版正文' '$TMP/live/live_公众号排版.html' && ! grep -q '/__version' '$TMP/live/live_公众号排版.html'"
kill "$LIVE_PID" 2> /dev/null || true
LIVE_PID=""

# 坏稿件：** 没配对
printf '# 标题\n\n这句**没有闭合。\n' > "$TMP/bad.md"
check "** 没配对时退出码为 1" "! R '$TMP/bad.md' --out '$TMP' > '$TMP/bad.log'"
check "报出没配对的 **" "grep -q '没配对的' '$TMP/bad.log'"

# 坏片段
printf '<section class="x" style="margin:0;line-height:2em;"><span style="font-size:16px;">a</span></section>\n<section><span>b</span></section>\n<section style="margin:0;font-size:16px;line-height:2em;"><img src="配图/01.png" style="width:100%%;"></section>\n' > "$TMP/badfrag.html"
check "坏片段退出码为 1" "! R --check-file '$TMP/badfrag.html' > '$TMP/badfrag.log'"
check "报出 class" "grep -q 'class' '$TMP/badfrag.log'"
check "报出缺行内样式" "grep -q '缺行内样式' '$TMP/badfrag.log'"
check "报出本地图片地址" "grep -q '不是公网地址' '$TMP/badfrag.log'"
check "报出缺字号或行高" "grep -q '缺字号或行高' '$TMP/badfrag.log'"

echo "pass=$pass fail=$fail"
[[ $fail -eq 0 ]]
