# draft_plan.json 写法

`build_draft.py` 只读这一个计划文件，外加它引用的品牌包和素材清单。计划里只写这条片子自己的东西：镜头、运镜、转场、说明文字和时间。说明长什么样、底衬多深、边框什么颜色，都在品牌包 `brand.json` 的 `jianying` 段里，不在计划里重复写。

相对路径都相对于计划文件所在的目录。帧号都是全片帧号，区间左闭右开。

## 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 是 | 草稿名。staging 目录和安装后的草稿都用这个名字；每个新版本换一个名字 |
| `fps`、`canvas`、`total_frames` | 是 | 例如 30、[1920,1080]、2216 |
| `brand` | 是 | 品牌包 `brand.json` 的路径 |
| `source_canvas` | 有录屏运镜时 | 录屏像素尺寸，例如 [1920,1056]。运镜换算靠它 |
| `sanitize_manifest`、`segments_manifest` | 用到时 | `sanitize_clips.py`、`cut_segments.py` 的清单 |
| `main` | 是 | 主画面，必须从 0 首尾相接铺到 `total_frames` |
| `pip` | 否 | 画中画（生成视频这类小窗素材） |
| `cameras` | 否 | 可以被多个片段共用的运镜，按名字引用 |
| `chapters`、`captions` | 否 | 章节标签、说明 |
| `caption_avoid` | 否 | `{"enabled": true, "limit_bottom_px": 860}`：说明在下方时，目标底边要高于这条线 |
| `bgm` | 否 | `{"path": "...", "volume": 1.0}`，时长必须够全片 |
| `font_mode` | 否 | 覆盖品牌包的 `system`、`library`、`default` |
| `track_names` | 否 | 改轨道名，例如 `{"pip": "生成视频"}` |
| `overlays` | 否 | 品牌图层：原生图片和文字，见下文 |
| `staging`、`generated_dir` | 否 | 默认 `staging/`、`素材/生成/` |

## main：主画面镜头

```json
{"id": "01", "start": 222, "end": 333, "from_sanitized": "01",
 "camera": [{"op": "set", "rect": [0, 0, 1920, 960], "fit": true},
            {"op": "ease", "from": 242, "to": 250, "rect": [1160, 655, 760, 427.5]},
            {"op": "punch", "f": 306}],
 "transition_out": {"name": "横移模糊", "frames": 8}}
```

- 素材三选一：`from_sanitized`（打码切片清单里的 id）、`from_segment`（烘焙段清单里的 id）、`media`（直接给文件路径，图片也行）。
- 可用帧不够镜头长度时，后面自动接一张末帧定格。定格帧取自已打码的素材。
- `source_in` 可以覆盖入点（素材内帧号），`live_frames` 可以限制可播帧数。
- 有 `camera` 的镜头算录屏，默认在说明期间垫底衬；`"scrim": false` 关掉。烘焙段不写 camera。
- `transition_out` 挂在这个镜头的最后一段上，名字是 pyJianYingDraft `TransitionType` 的成员名。

## 运镜操作

按顺序执行，结果是每个关键帧的（缩放, x 位移, y 位移）。

| op | 参数 | 作用 |
|---|---|---|
| `set` | `f`（缺省为镜头起点）、`rect` 或 `cam`、`fit` | 设定取景。`rect` 要是画布比例；`fit: true` 时取框内最大的画布比例矩形。也可以直接给 `cam: [s, tx, ty]` |
| `ease` | `from`、`to`、`rect` 或 `cam` | ease-out 推到目标，`to` 帧到位。剪映只有线性插值，这里用 7 个预采样点近似 |
| `hold` | `f` | 在这一帧钉住当前值。后面接一个 `set` 做切页跳变时，前面要先 `hold`，不然会从更早的点线性滑过来 |
| `punch` | `f`、`amount`=1.03、`attack`=4、`release`=8 | 冲击推近再回原取景，取景中心不动。「收一点」的版本用 1.03，不震屏 |
| `pop` | `f`、`cam`、`amount`=0.97、`attack`=4、`release`=5 | 画中画的节拍弹跳：平时缩在 cam×amount，`f` 帧弹回 cam。只缩放，不动位置 |

运镜框越出源画面会直接报错，因为那样会露出黑边。

## pip：画中画

```json
{"id": "16A", "start": 1552, "end": 1580, "from_sanitized": "16", "source_in": 62,
 "camera": "16", "intro": {"name": "放大", "frames": 6}}
```

- 同一个文件的几个片段共用一个素材，在剪映里「替换素材」时会一起换。
- 默认带一条同尺寸的边框轨，关键帧和入场跟视频完全一样；`"border": false` 关掉。
- `camera` 可以引用 `cameras` 里的名字，几个片段共用同一条运镜。

## overlays：品牌图层

把 logo、品牌字这类原本要烘焙进底片的东西做成剪映原生的图片和文字，用户能在剪映里直接改字、换 logo、调位置。底片里只留剪映做不出来的光效和 3D。

```json
"overlays": [
  {"name": "品牌-logo", "kind": "image", "items": [
    {"id": "开场_logo", "media": "素材/品牌/logo.png", "start": 27, "end": 447,
     "keys": [{"f": 27, "x": 596.5, "y": 470, "h": 120}, {"f": 34, "x": 596.5, "y": 470, "h": 200, "ease": "out"}]}]},
  {"name": "品牌-名称", "kind": "text", "items": [
    {"id": "开场_名称", "text": "示例品牌", "px": 150, "bold": true, "color": "#EEF4FF", "start": 36, "end": 447,
     "intro": {"name": "羽化向右擦开", "frames": 12}, "keys": [{"f": 36, "x": 1105.5, "y": 470, "scale": 1}]}]}
]
```

- 每层一条轨，叠在主画面、画中画之上，底衬、章节、说明之下；同一层里的片段不能重叠，重叠的放两层。
- 坐标是画布像素，x、y 是中心点。图片的 `h` 是显示高度（素材先按比例 fit 进画布再缩放），文字的 `scale` 是缩放倍数，`alpha` 缺省 1。
- 关键帧之间剪映只有线性插值；某个 key 带 `"ease": "out"` 时，从上一个 key 到它按三次 ease-out 预采样 7 点；`"ease": "inout"` 按三次慢进慢出预采样 11 点（大位移、缩放用它，ease-out 开头太猛）。
- 文字的 `letter_spacing` 是剪映的字间距值，导出为 值×0.05 倍字号。
- `intro`、`outro`：文字用 TextIntro / TextOutro 的成员名，图片用 IntroType / OutroType。
- 文字也走品牌包的字体设置（system 模式指向系统兰亭黑，剪映按第 0 个字形即中黑渲染，`bold` 是剪映的加粗）。
- 文字可选 `shadow`（`alpha`、`color`、`diffuse`、`distance`、`angle`）和 `border`（`alpha`、`color`、`width`），数值和剪映文本面板一致。旁白字幕压在录屏上时用阴影。
- 旁白要在剪映里文本朗读时，把每句做成一层文字的一段；画面上已经有字的句子放在 `alpha: 0` 的单独一层，只供朗读。
- `verify_draft.py` 核对每段图层在不在、时间对不对、文字内容对不对。

## captions：说明

```json
{"text": "评分 94 · 门槛 75", "start": 998, "end": 1047, "slot": "top",
 "target": {"rect": [1040, 560, 880, 495]}}
```

- `slot`：`bottom`（默认，品牌包的 `center_y_px`）或 `top`（`top_center_y_px`）。目标贴着录屏底边、下方会盖住它时才用 top。
- `target`：说明要讲的那个界面元素，源画面坐标。页面滚动或切页时写 `{"keys": [{"from": 帧, "rect": [...]}, ...]}`。
- 有 target 的说明会参与避让：同一镜头里只上移取景，不改缩放，录屏底边不露出；做不到的帧写进 `build_manifest.json` 的 `caption_clearance.exceptions`，校验时算警告，交付时要在说明里写出来让人看。
- 字数控制在一行内，品牌包 `max_width_px` 是上限，超了构建直接报错。

## 产出

`staging/<name>/` 下是明文草稿和 `build_manifest.json`。之后：

```bash
python verify_draft.py staging/<name>
python preview_layout.py staging/<name>
python jy_install.py --staging staging/<name> --draft-root <草稿库> --check
python jy_install.py --staging staging/<name> --draft-root <草稿库>
```
