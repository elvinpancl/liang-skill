---
compositionId: <作品-id>
duration_frames: <总帧数，等于剪好的音乐 ceil(秒×30)>
canvas: { w: 1920, h: 1080, fps: 30 }
music: assets/bgm.mp3（<版本>，<BPM> BPM，网格残差 <ms> ms）
timing: data/timing.json（make_timing.py 由 accents.json 生成，全部锚点以此为准）
brand: <品牌包路径>/brand.json
assets: "assets/clips/ 录屏粗剪；assets/cards/ 裁切卡；取证 shots.json 给出总览框、聚焦框和敏感区"
delivery: "HyperFrames 底片（只烘焙开场、3D 段、片尾）+ 剪映可编辑工程（liang-promo-jianying）"
avoid:
  - "简单淡入淡出转场"
  - "全屏闪白超过一次、震屏、色差（转场收一点）"
  - "纯黑底：开场和 3D 段用品牌背景"
  - "说明少于 36 帧、同屏两条、压住它要讲的目标"
  - "录屏里没有的能力；任何敏感区；穿模的生成视频"
---

# 全片规则

1. **卡点分级**（按 accents.json 的 level）
   - heavy：切镜、大转场、品牌落定
   - medium：推近、文字砸入、界面高亮
   - light：逐字、角标、光扫
   - 切点放在小节第一拍。重拍段常见「第 4 拍、第 4 拍后半、下一小节第 1 拍」三连击，用来砸三个词。
2. **录屏取景**：地址栏露出项目编号的片段，总览从地址栏下沿起取景；底部有敏感缩略条的，总览下沿不越过它。
3. **敏感区**：shots.json 每个 sensitive 矩形在它的时间段内入画就打码，随运镜跟随。
4. **说明**：一行、不超过 10 个字，用词来自配音稿或界面原文；剪映版统一放下三分之一。
5. **生成视频**：先按 liang-promo-beat 的筛查选干净镜头；原片没到时用录屏预览区做影片卡，最大约 2 倍，不铺满全屏。

# 章节

| 编号 | 章节名 | 覆盖范围 |
|---|---|---|
| 01 | <能力 1> | F2 |
| 02 | <能力 2> | F3 |

---

## Frame 1 — f1-opening

- src: compositions/frames/01-f1-opening.html
- span_frames: [0, <第 5 小节起始帧>]
- pacing: beat_cut
- feel: <这一段的情绪，一句话>
- bake: yes（开场文字和品牌组合烘焙进底片）

### Groups

- **g1** — `textSlam + brandBackdrop`：<画面一句话>
  - span_frames: [0, 42]
  - anchors: [1]（S：砸入峰值）
  - copy: 「<文字>」
- **g2** — ...

## Frame 2 — f2-<能力>

- src: compositions/frames/02-f2-<能力>.html
- span_frames: [<起>, <止>]
- pacing: beat_cut
- bake: no（录屏段在剪映里原生运镜）

### Groups

- **g1** — `camera + callout`：<片段号> 总览 → 推到 <目标>
  - span_frames: [..]
  - source: <片段号> [<入点秒>, <出点秒>)
  - camera: 总览框 → 聚焦框 F<n>（shots.json），推近在锚点帧到位
  - anchors: [<帧>]（S：切入）、[<帧>]（R：推近到位）
  - copy: 「<说明>」，停留 [<起>, <止>)，≥36 帧
