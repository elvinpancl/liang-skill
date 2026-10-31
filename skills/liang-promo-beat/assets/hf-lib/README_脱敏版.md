# HyperFrames 动效组件库

一套给卡点展示片用的帧驱动组件：录屏运镜、指向说明、章节标签、文字砸入、闪光、冲击推近、甩镜、色差、打码，6 个 3D 场景（空间飞行、环形画廊、终端窗飞行、卡片翻飞收束、克隆纵队、扫描线装配），品牌背景和 logo 组合，影片卡。通用组件由 Codex 辅助实现；3D 场景的数学移植自 video-shotcraft（Apache-2.0，见 `LICENSE-shotcraft`），各文件头注明了出处。

## 怎么接进 HyperFrames 工程

- 工程结构：源稿放 `src/*.html`，产物写 `compositions/frames/`。源稿 `<template>` 里留 `/* FX_JS */`、`/* FX_CSS */` 两个位置。
- 构建：`node <skill>/scripts/build-frames.mjs --project <工程> --brand <品牌包>/brand.json --accents <accents.json> [--plate]`。它把本目录的 JS、CSS 内联进每个子合成，按源稿里的 `FX.<组件>` 调用挑需要的模块（间接调用时写注释 `FX_USE: scenes-spatial` 之类声明），并在最前面注入 `window.FX_BRAND`（品牌包生成）和重拍帧号 `FX.brandHeavyFrames`。
- 品牌：颜色、字体族、logo、名称、口号都读 `FX.brand`，组件代码里没有写死的品牌。`colors.accent` 不给时等于品牌色。
- GSAP：工程自己放一份 `lib/vendor/gsap.min.js`，宿主 index.html 加载它。本库不附带 GSAP；从已有工程复制，或经同意后从 npm 的 `gsap` 包取。
- `--plate` 时额外内联 `jianying-plate.css`：隐藏说明、章节这些交给剪映原生文字的元素，只留 3D 段内部文字和打码，用来渲染给剪映切段的底片。
- 字体先 `document.fonts.load('700 160px <字体族>')`，图片全部 `decode()` 之后再注册 `window.__timelines[id]`，避免空时间轴和替代字体测量。
- `core.js` 的 `drive(tl,opts,renderAt)` 为每个组件建一个 `{f:0}` 代理，线性覆盖段长；所有状态都由当前帧直接算出，可以正序、逆序、跳帧 seek。同一元素的同一属性不要挂第二个控制器，复合效果用包装层。

## 转场的峰帧语义

五个转场的 `peakF` 统一表示「视觉变化最剧烈的那一帧」。帧差 `D[f] = |I[f] − I[f−1]|`，主攻击落在 `(peakF−1, peakF]`，这样 `beat_check.py` 回测时峰正好落在锚点上：

| 组件 | 峰帧语义 |
|---|---|
| whip | 主要横移、方向模糊峰值；不是几何半程。出画层前 3–4 帧加速，锚点帧硬切，入画层后 4–5 帧减速 |
| crashZoom | 加速推近后的换镜与闪光峰值；禁用闪光时仍同帧切层 |
| flash | 从 0 跳到最高不透明度的帧；白到品牌金的径向闪光，3–6 帧指数衰减，不留平铺色块 |
| chromaticSplit | 通道偏移的主要跃迁与最大分离 |
| textSlam | 全部文字同时完成主要缩放、去模糊与显现；逐字只错开预备 |

素材自己的跳变也会产生帧差峰。如录屏片段在转场前自行翻页，可能产生额外帧差峰；应检查源素材与组件的峰帧语义，不要用统一偏移掩盖问题。

## 排版审计

HyperFrames 0.8.181 的排版审计会把 3D 场景正常的前后遮挡报成错误。只给 3D 层和遮罩层加 `data-layout-allow-overlap`、`data-layout-allow-occlusion`、`data-layout-ignore`；说明文字、章节标题、普通二维字幕、计数器不豁免，真实的二维文字冲突仍要报出来。整片跑 `hf check` 会超时，整片只跑 lint，卡点由渲染后的 `beat_check.py` 验。

## 约定

参数时间统一用段内帧号，HyperFrames HTML 的 `data-start`、`data-duration` 仍用秒，两者通过 `fps` 换算。中文说明字不小于 40px；放大截图保留原比例，不把放大说成增加分辨率。真正的像素、滤镜、3D 遮挡效果要渲染出来看。

# 共用组件

加载顺序为 `core.js`、`common.js`。所有 API 都是 `ZRFX.<名称>(tl, opts)`，把确定性动画加入调用者的同一个暂停 GSAP 时间线，不创建或注册第二条合成时间线。共同参数为 `container`（本段 DOM 容器）、`durationF`（本段总帧数，必填）、`fps`（默认 `30`），所有 `*F`、关键帧 `f`、`renderAt(f)` 都使用段内帧号；允许小数帧。组件返回 `{element, renderAt, ...}`。`renderAt` 由输入帧完整重算其负责的样式，可正序、逆序或跳帧调用。

字体是品牌包的字体族（`FX.brand.font`），本地加载。源码不读取时钟、鼠标或上一帧，不使用无种子随机数。视频仍由 HyperFrames 的 `data-start`、`data-duration`、`data-media-start` 驱动，组件不操作播放头。默认视口为 `1920×1080`。挂载共享代码时须使用工程构建脚本内联到子合成 `<template>`，不能依赖子合成外的 `<head>`。

## camera：录屏运镜

参数：`element` 为源视频或图片 DOM；`keyframes:[{f,rect:[x,y,w,h],ease}]` 为源坐标裁切框；`sourceWidth/sourceHeight` 默认 `1920/1056`，`width/height` 默认 `1920/1080`。目标关键帧的 `ease` 控制从前一关键帧抵达该帧的插值，可使用 `smooth/out/linear/inOut`、GSAP 缓动字符串或纯函数。默认平滑插值。裁切框按等比铺满映射到视口，非 `16:9` 的框会按 cover 居中裁边，画面不拉伸。

帧语义：第一个关键帧之前保持首个裁切框，最后一个之后保持末个裁切框。返回 `punch(f,amount=0.08)` 在 `f` 达到冲击峰值，前 `2` 帧起势、后约 `17` 帧回弹；`shake(f,px=8)` 从 `f` 开始约 `12` 帧衰减震动。两者可多次调用，参数变化纳入同一个纯函数，注册后立即刷新当前帧，支持 0 帧冲击。`screenRect(srcRect,f)` 返回屏幕矩形 `[x,y,w,h]`，包括当帧的推近和震动；`matrixAt(f)` 返回 `{scale,x,y}`，`cropAt(f)` 返回插值后的源矩形。camera 只改变自己创建的非 timed 包装层，不改媒体时间参数。

用法：`const cam = ZRFX.camera(tl,{container:stage,element:video,durationF:120,keyframes:[{f:0,rect:[21.3333333333,0,1877.3333333333,1056]},{f:45,rect:[1040,560,880,495],ease:'out'}]}); cam.punch(55,.06).shake(55,5);`。需要贴住源图区域的说明框和隐私遮挡均传入同一个 `cam`，不要重复手算屏幕坐标。

## callout：指向说明

参数：`text` 为不超过 `10` 个非空白字符的一行文字，数字与标点计数，排版空格不计数；`camera` 与 `srcRect` 指定源图目标框。固定屏幕目标可省略 camera，使用 `rect`；动态自定义目标可传纯函数 `target(f)` 返回 `[x,y,w,h]`。`labelPos:[x,y]` 为文字框左上角，默认 `[140,820]`；`fontSize` 默认 `48` 且最小 `40`；`startF/endF` 为显示窗口，`zIndex` 默认 `20`。`scope` 默认为最近的合成根，跨镜头容器可显式传同一个根来共享互斥日程；`exitF` 默认为 7，限定 6–8 帧。`cutF/targetEndF` 为硬截止帧，`targetVisible(f)` 可提供目标是否可见的纯函数。

帧语义：`startF` 开始四角从外扩 `26px` 咬进到 `8px`，约 `7` 帧完成；细连接线随后伸出，文字从第 `6` 帧开始按 `1.25` 帧错峰逐字升起。结束前 `exitF` 帧角标外退、文字快速收回，在 `endF` 完全隐藏。同一 scope 中若下一条更早开始，上一条提前 6–8 帧退场并在下一条开始前完全消失，任何时刻最多一条。目标完全离开视口、`targetVisible(f)` 为假或到达 `cutF/targetEndF` 时整个说明立即隐藏。`enterF` 可改角标入场长度；`revealF` 可指定所有文字与连接线在多少帧内完整出现，0 表示立即出现。角标使用 scanline 参考的四个 `22px` L 角，源矩形位置每帧取自 `camera.screenRect`；连接线选择靠近文字的边界，不指向目标内部。

用法：`ZRFX.callout(tl,{container:stage,durationF:120,camera:cam,srcRect:[1264,967,312,76],text:'质量评分 94',labelPos:[330,550],startF:45,endF:113});`。返回额外 `label` 供调用者定位，但不建议让另一组件同时修改其 transform 或 opacity。

## chapterTag：章节标签

参数：`number` 默认 `'01'`、`previousNumber` 默认当前编号减一（下限 0）、`title`、`position` 默认 `[80,72]`、`startF/endF`；`zIndex` 默认 `30`。标签使用 `58px` 数字及 `48px` 标题，编号为两位补零的整号滚轮，只有上一章节号与当前章节号两行；例如 09 → 10 不经过其他数字。标题从底部金线下升起。

帧语义：从 `startF` 起先亮出编号，数字约 `18` 帧滚动停靠；标题第 `7` 帧开始上升，约第 `23` 帧就位。结束前 `6` 帧向上退场。滚轮位置由当前帧直接计算，不根据上一次显示的数值推进。

用法：`ZRFX.chapterTag(tl,{container:stage,durationF:120,number:1,title:'写故事',startF:0,endF:115});`。

## textSlam：文字砸入

参数：`text`、`peakF`、`fontSize`（默认 `132`）、`color`（默认正文色）、`perChar`（默认否）、`staggerF`（逐字模式默认 `2`）、`attackF`（默认 `5`）、`shakePx`（默认 `6`）、`endF`。`shakeElement` 可指定底图层，与文字同步轻微震屏；未指定时只震动文字。也可传已有 `element`，由组件包装后施加整块冲击；已有元素模式不拆字。

帧语义：`peakF` 是整条标题视觉变化最剧烈的帧，主缩放、去模糊、显现集中在 `(peakF-1, peakF]`。此前只做低强度预备，同帧达到泛光与轻震峰值，之后轻微回弹。`perChar/staggerF` 只错开预备动作，所有字在同一个 `peakF` 完整落位，不把末字冲击延到锚点之后。结束前 `5` 帧淡出。停留时文字完全清晰，泛光有界衰减。

用法：`ZRFX.textSlam(tl,{container:stage,durationF:120,text:'故事开始',peakF:18,fontSize:160,perChar:true,staggerF:2});`。较长文案需主动设置合适字号，保持主标题在安全区域内。

## flash：白闪或金闪

参数：`peakF`、`flashF`（默认 `5`，限制 `3–6` 帧）、`color`（`'white'`、`'gold'` 或 CSS 色值）、`opacity`（默认 `1`）、`zIndex`（默认 `90`）。这里 `durationF` 始终是段总帧数，闪光长度只由 `flashF` 控制。

帧语义：`peakF` 精确到达峰值，之后作归一化指数衰减，在 `peakF+flashF` 归零，之前不亮。它不会自行切换底层内容。

用法：`ZRFX.flash(tl,{container:stage,durationF:120,peakF:60,flashF:4,color:'gold'});`。

## crashZoom：冲击推近转场

参数：`a/b` 为先后两层 DOM，`peakF` 为视觉变化最剧烈的闪白切层帧；`point:[x,y]` 默认画面中心，`scale` 默认 `3.4`；`attackF` 默认 `8`，`settleF` 默认 `12`；`flashF` 默认 `4`，`flashColor` 默认白色。组件为两层创建独立非 timed 包装层，避免覆盖内部组件运镜。

帧语义：从 `peakF-attackF` 起按指数加速向 `point` 推近，模糊依据纯函数中心差分速度生成；`peakF` 隐藏 A、显示 B，并白闪；B 从 `1.07` 回弹到 `1`。峰帧后 A 不会再显示，B 保持清晰。返回额外 `{a,b,flash}`。

用法：`ZRFX.crashZoom(tl,{container:stage,durationF:120,a:layerA,b:layerB,peakF:60,point:[1370,650],scale:3});`。不要同时对相同 A/B 包装层应用其他控制 opacity 或 transform 的组件。

## whip：甩镜转场

参数：`a/b`、`peakF`、`direction`（默认 `'left'`，另支持 `right/up/down`）、`halfF`（峰前与峰后各 `6` 帧）、`blurPx`（峰值默认 `32`）。横向用 SVG 高斯模糊 `stdDeviation="x 0"`，纵向用 `"0 y"`，是沿运动方向的拖影。

帧语义：从 `peakF-halfF` 到 `peakF+halfF`，A 移出、B 从相反侧同步移入；`peakF` 表示视觉变化最剧烈的帧，不再表示半程。约 81% 的画面位移集中在 `(peakF-1, peakF]`，到峰帧已完成 92% 路程，方向模糊同帧最大，随后减速归位。结束时 A 隐藏、B 精确归零位移，滤镜移除。返回额外 `{a,b,sampleAt}`，`sampleAt(f)` 给出进度、位移与模糊强度。SVG 标识由容器名加共享确定性构建计数生成，多段内联不会重名。

用法：`ZRFX.whip(tl,{container:stage,durationF:120,a:layerA,b:layerB,peakF:60,direction:'left',halfF:6});`。

## chromaticSplit：RGB 通道分离

参数：`element` 为要分离的实际内容 DOM，也接受 `target` 别名；`peakF`、`amount`（峰值偏移默认 `24px`）、`riseF`（默认 `2`）、`decayF`（默认 `14`）。组件在独立包装层上将实际内容分成红绿蓝三通道，以相反偏移合成，不用装饰边框模拟，不复制或驱动视频播放头。

帧语义：`peakF-riseF` 开始低强度预备，`peakF` 集中完成通道分离，是最大单帧参数变化与最大偏移帧；之后指数衰减，在 `peakF+decayF` 恢复中性并去除滤镜。全部通道偏移每帧重算；多个合成的 SVG id 互不冲突。

用法：`ZRFX.chromaticSplit(tl,{container:stage,durationF:120,element:heroLayer,peakF:70,amount:28,decayF:12});`。

## mask：敏感区域跟随打码

参数：`camera`、`srcRect`（或固定屏幕 `rect`）、`startF/endF`、`padding`（默认 `5px` 安全外扩）、`blurPx`（默认源坐标 `40px`，最小 `32px`）、`darkness`（默认 `0.35`，限制为 `0.25–0.45`）、`zIndex`（默认 `15`）。使用强背景模糊 `backdrop-filter` 配合约 35% 暖黑半透明叠层；字体、图片等被遮挡内容的原件不改动。

帧语义：在 `[startF,endF)` 全程立即覆盖，不作可能泄露原文的入退场淡化。位置、尺寸每帧由 `camera.screenRect` 计算，同步包含推近与震动；安全外扩在屏幕像素坐标中执行。模糊半径按相机缩放同步放大，且屏幕半径不少于 48px，避免被放大的字形从固定模糊半径中重新显露。不能把遮挡层放进 camera 已经变换的源层，否则会二次变换。此实现依赖系统 Chrome 的 `backdrop-filter` 支持，实际覆盖范围需通过渲染逐帧核验。

用法：`ZRFX.mask(tl,{container:stage,durationF:120,camera:cam,srcRect:[160,44,1604,40]});`。多个敏感矩形分别调用，多层遮挡均应位于源画面上方、字幕与说明框下方。

## 参考差异与验证边界

共用组件的颜色和字体都来自品牌包（`FX.brand`）。计数和文字配方中的历史值判断、全局 selector、相对累计位移均已改为帧的纯函数。白闪由原配方的硬亮灭改为 `3–6` 帧指数衰减；甩镜增加单轴拖影；RGB 改为处理实际内容的通道滤镜。camera 的取景和隐私遮罩为本项目新增数学映射。动画端点、确定性以及 SVG 通道数可静态或以 DOM 状态验证；像素、真实 Chrome 模糊及视频提取效果仍以测试片渲染证据为准。


# 空间组件参数

这三个组件移植自 `参考_shotcraft/demos/`，来源提交为 `43bd349a136651865ecfa6ea1cf012f6e957d304`，原作者 Wei Yihao，Apache-2.0。加载顺序为 `core.js`、`common.js`、`brand-backdrop.js`、`scenes-spatial.js`。全部调用采用 `ZRFX.<name>(tl, opts)`；`tl` 是调用方的 GSAP 时间轴，`opts.container` 是当前段 DOM，`durationF` 是段总帧数，`fps` 默认 30。组件通过代理对象加入时间轴，独立返回 `renderAt(f)`；同一个输入帧可反向或重复调用。调用方负责在构建完成后注册时间轴。

所有时间均为段内帧号，允许小数帧。所有空间均为 1920×1080 坐标，`pose` 结构为 `{x,y,z,rx,ry,rz,s}`，角度为度、缩放默认 1。正变换和相机逆变换严格反序；不得把旋转顺序换掉。组件的所有中文原生 DOM 说明字均不少于 40px；截图中已有文字是原始素材内容，无法通过放大获得新细节。图片保持原比例；basic3dScene 与 carousel3d 保留原生尺寸上限，terminal3d 按任务 05 默认放大 2.1 倍。给定素材名的原尺寸已内置，也可显式传 `nativeSize:[w,h]`。

## basic3dScene

参数：`stations:[{img,pose,label,nativeSize?,maxWidth?,maxHeight?,minWidth?,minHeight?}]`；`flights:[{from,to,startF,landF}]`，站点索引从 0 开始，飞行区间必须不重叠且前后相接；`overview:{startF,landF,scale,pose?,label?}` 可省略。`perspective` 默认 3000，`hop` 默认 0.3，`creep` 默认 0.015，`dustCount` 默认 60。默认截图最大显示范围为 1740×820，使用原图缩小装入卡框；小图以原像素居中，卡框最小 720×420。五站可分别提供不同宽高。总览未指定姿态时以站点包围范围的中心为中心，采用 `scale` 拉远。

帧语义：`startF` 从 `from` 站起飞，`landF` 精确对齐 `to` 站；飞行中以正弦包络拉远。停留期间缓推，并在下次起飞前恢复基准；因此精确落位帧不带额外缩放。总览期间所有卡片逐渐回到可见焦点。离焦卡透明度和 0–7px 景深只作用于单卡叶层，浮尘固定在世界坐标产生真实视差。返回 `{element,renderAt,sampleAt,cards,world,proxy}`；`sampleAt(f)` 返回相机姿态、站点进度和总览进度。

用法示例：`ZRFX.basic3dScene(tl,{container:stage,durationF:150,stations:[{img:'assets/cards/flight_story.png',label:'故事',pose:{x:0,y:0,z:0}},{img:'assets/cards/page_script.png',label:'剧本',pose:{x:2000,y:200,z:-500,ry:-28}}],flights:[{from:0,to:1,startF:36,landF:64}],overview:{startF:100,landF:130,scale:3,label:'从故事到成片'}})`。调整实际画面布局时优先修改 `pose` 与总览中心，保持逆变换数学不变。

## carousel3d

参数：`cards:[{img,label,nativeSize?}]`（也接受 `items`），字符串图片数组可用但不提供字幕。`stepLandF:[0,21,42,...]` 指定每次停靠的帧，默认均匀分配一整圈；第一项对应第 0 张卡，后续每项顺次前进一张，超过 N 后循环。`dwellF` 默认 5，最多占相邻停靠区间的 40%；`radius` 默认 690，`cardWidth` 默认 340，`cardHeight` 默认 460，`perspective` 默认 2200，`tilt` 默认 −9，`centerY` 默认 465，`push` 默认 34，`highlightAngle` 默认 26。素材尺寸为 206×190 时原像素居中，外围用原生 DOM 排编号及两行卡名。

帧语义：在每个 `stepLandF[k]`，第 `k % N` 张卡的方位角精确为 0；停靠后短暂停留，随后 smooth 曲线换位。为满足指定帧精确停靠，这里取消参考版的 50% 匀速底，保留环形公转、点亮、外推、字幕滚动。双面都用同一份内容，背面仅 `rotateY(180deg)`；正反面均有标准与 WebKit 背面隐藏。反射是以地面翻转的第二个完整 3D 环，8% 透明度与渐隐仅施加在面层。返回 `{element,renderAt,sampleAt,cards,reflections,ring,proxy}`；`sampleAt(f)` 含 `spin`、`selected`、`progress`。

用法示例：`ZRFX.carousel3d(tl,{container:stage,durationF:130,cards:styleCards,stepLandF:[0,16,32,48,64,80,96,112,128],dwellF:4})`。8 张卡配 9 个停靠帧可回到第一张卡；第一张与最后一张应使用相同正面位置检查双面、倒影与循环方向。

## terminal3d

参数：`windows:[{img,title,typeText,pose,nativeSize?,cardScale?,typeStartF?,typeEndF?,view?,width?,height?}]`。`cardScale` 可顶层设置或逐窗覆盖，默认 `2.1`；窗口由放大后卡片加 64px 横向留白、218px 标题与上下留白自动计算，前两窗约 894×428、冻结窗约 1776×539。显式 `width/height` 仍可限制窗口，图片按 contain 适配。`flights` 同 `basic3dScene`，也接受相邻站飞行的 `[[startF,landF],...]`；`typing:[[startF,endF],...]` 或 `[{startF,endF},...]` 可在顶层给定每窗打字区间，窗口自身参数优先。`perspective` 默认 2200，`tilt` 默认 −3，`viewAngles` 默认 `[8,-8,9]`，`pullPeak` 默认 1250。标题为 48px，逐字文案为 52px，位于同一标题栏的第二行；内容区基本由放大卡片铺满。亮玻璃渐变底配 2px 金色描边。

帧语义：每窗打字起点不得早于到站；默认在到站后 3 帧开始，以固定散列权重分配逐字时间，`typeEndF` 时完整显示。光标打字期间常亮，结束后按 8 帧半周期闪烁。窗间飞行中用 `sin(π·raw^0.85)×pullPeak` 拉远，拉远时景深变深，落位时当前窗滤镜清零。SVG 地面逐线投影与 CSS 相机逆变换同构，包括复合 X/Y/Z 旋转与缩放。默认保留小角度侧视；若需要严格正视原生像素验收，传 `tilt:0,viewAngles:[0,0,0]` 并选择开场推近结束后的停靠帧。返回 `{element,renderAt,sampleAt,projectAt,cards,world,typing,proxy}`。

用法示例：`ZRFX.terminal3d(tl,{container:stage,durationF:150,windows:[{img:'assets/cards/terminal_step01.png',title:'故事方向',typeText:'找到故事的方向'},{img:'assets/cards/terminal_step02.png',title:'剧情主线',typeText:'铺开剧情主线'},{img:'assets/cards/terminal_frozen.png',title:'规划冻结',typeText:'规划已冻结'}],flights:[[38,58],[90,110]],typing:[[8,25],[60,78],[113,129]]})`。原前两张为 395×100、冻结卡为 815×153；默认显示为 829.5×210、1711.5×321.3。放大便于观看，不增加源图细节。`cards` 同时返回 `body/width/height/cardScale` 便于核对尺寸。

## 与参考的明确差异

色板统一为暖黑、金、品牌绿；真实截图代替参考手绘占位 UI。画廊保持原尺寸截图；终端按任务 05 放大，并缩紧窗口空白，未伪造新图像细节。轮播改成指定帧准确停靠，停留不叠匀速漂移；空间相机采用可复用的 smooth/inOut 缓动，未复刻参考里的自定义贝塞尔与时间子帧运动模糊。终端简化为真实截图与标题栏打字，未复制占位 CLI 输出、背光光池或结果状态。以上差异均不影响确定性寻帧、双面贴图与相机数学。


# 装配与收束组件

加载顺序：`core.js` → `scenes-assembly.js`。三个函数都向传入的 GSAP timeline 加入线性帧代理，返回 `element`、`renderAt(f)`、`proxy` 及各自辅助字段。`f` 和所有 `*F` 参数均为段内帧号，默认 `fps:30`；`durationF` 和 `container` 必填。容器按 1920×1080 设计，全部帧状态由纯数学计算，不读时钟。外层由调用者负责 HyperFrames 时间窗，库不注册 composition timeline。

## cardFlockTumble

参数：`images` 必须为三张整页图片的地址；`flightStartF:8`、`flightLandF:46` 控制连续 Catmull-Rom 翻飞；`collapseF:58` 是收束起点，固定持续 10 帧；`slamF` 默认为 `collapseF+14`；`sloganF` 默认为 `slamF+16`；`brand`、`slogan` 缺省读品牌包，可在调用时替换。`center:[960,570]`、`cardSize:[700,385]` 控制卡组几何。`fontSize:160` 为最大字号，`textMaxWidth:1680` 为包含 1.22 倍砸入峰值的最大文字宽度，初始化时测量并缩小字号。建议调用者在字体加载完成后建 timeline。`id` 可指定烟环 SVG 的标识前缀。

帧语义：`flightLandF` 前进入阶梯，飞行末段叠加平方缓入慢转，到 `collapseF` 连续吸入；卡片全程不加 blur，收束前 60% 保持完全不透明。`collapseF+10` 同帧触发白热闪核与单个湍流烟环；`slamF` 须不早于该帧。烟环叠加四个同半径噪声层来塑造一个烟雾体，噪声 seed 固定为 11、37、73。返回额外的 `cards`、`cardPoseAt(f,index)`、`coreF`、`slamF`。

```js
ZRFX.cardFlockTumble(tl, {
  container: document.getElementById('flock'), durationF: 120,
  images: ['assets/cards/page_script.png', 'assets/cards/page_character.png', 'assets/cards/page_storyboard.png'],
  flightStartF: 6, flightLandF: 42, collapseF: 58, slamF: 72
});
```

与参考差异：将 React 手绘界面换成真实图片；暖黑、金色与品牌绿代替极光色；巨字按实际中英文宽度收为约 160px；不带参考原品牌眉题。烟环保留静态固定噪声随整体旋转、长大的原配方，没有另加粒子。

## clonerDepthEcho

参数：`img` 为主卡，`clones` 为分身图片数组，单项可为地址或 `{img,label}`；`spawnF:20`、`staggerF:2.2`、`spreadDurationF:20` 定义逐个排开；`mergeF:72`、`mergeDurationF:10` 定义全体同步吸回；`cardRect:[90,245,960,710]`；`gapZ:100`、`dx:0`、`dy:0`、`perspective:1800`、`vanishingPoint:[1060,540]` 控制纵队。`title:'从剧本到角色场景'`、`counterLabel:'内容资产'` 可替换。`counterText` 可设置完整计数文案，正式片和测试片传「角色 3 · 场景 2」，`counterFontSize` 默认 64px；不传时保留数字计数模式。所有图使用 contain 保持原比例；主图最大放大 2 倍，分身最大 4 倍。分身可传 `nativeSize:[w,h]`、`cardRect`，也可顶层传 `cloneRects` 数组；默认按纵横比使用 400×600 或 440×380 窗口，前三张横向间距 185px，后两张收至 x=1450/1570 以保留过冲余量。标签在各卡停稳后显示，回收前 6 帧退完；场景标签错开纵向位置，仍按普通二维文字检查。

帧语义：主卡在第 0 帧已完全可见，位于左中且宽 960px；`spawnF` 前 8 帧按压，分身从主卡同一位置开始，以 `staggerF` 错峰飞向斜向纵深位置；最后分身到位之后才能设置 `mergeF`。合体帧 `mergedF = mergeF + mergeDurationF`，主卡单次弹跳与绿色边缘闪光同时触发，右下计数器保留文案并回弹。未设置 `counterText` 时每一分身出生 2 帧后计数加一，5 帧滚动；滚动过程中只显示一个数字，避免二维文字重叠。返回额外的 `hero`、`clones`、`depthAt(f,index)`、`mergedF`，`index` 从 1 开始。

```js
ZRFX.clonerDepthEcho(tl, {
  container: document.getElementById('clone'), durationF: 120,
  img: 'assets/cards/clone_script.png',
  clones: ['clone_linyue','clone_chen','clone_wife','clone_scene_cabin','clone_scene_cloud'].map(name => 'assets/cards/'+name+'.png'),
  spawnF: 20, mergeF: 70, counterText: '角色 3 · 场景 2'
});
```

与参考差异：分身换成角色与场景真实素材，保留各图片信息，因此不褪成纯线框；分身不额外叠加失焦 blur，文字保持清晰。弹出使用一次有限过冲，代替 Remotion 的物理弹簧求解。计数器使用明确的上下位移和透明度，不加参考的数字模糊。

## scanlineAssemble

参数：`blocks:[{img,slotRect:[x,y,w,h],from,landF?,label?,rotation?}]` 必填，槽位使用画板内坐标。`from` 为相对槽位的 `[dx,dy]`、`{x,y,rotate}`，或 `'left'|'right'|'top'|'bottom'`，方向形式自动保证起点完全在画面外；所有图片 contain。`boardRect:[288,160,1344,800]` 是画板屏幕位置，默认宽度占画面 70%；`maxScale` 默认 2.2，可由单个 block 覆盖，测试片槽位按原素材 1.8 倍设置，卡片按槽位 contain 放大；`scanStartF:8`、`scanEndF:86` 定义扫描窗口；`flightF:14` 是每块提前起飞的时长。

帧语义：扫描线严格匀速，从画板 y=-20 到 y=height+20；默认落位帧由槽位下缘反算，按下缘排序后自动保留最少 4 帧间隔。显式 `landF` 完全按传入帧执行，可对齐重音；这时调用者负责协调扫描线与槽位下缘。全部区块必须在 `scanEndF` 前落位，否则抛出参数错误。落位前 `flightF` 帧起飞、一次轻微过冲，方向拖影由相邻帧位移差分计算，停稳后清零；槽位说明在起飞前 7–3 帧退出，避免压在新卡片下面；落位后 1–14 帧显示四角咬合。画板底色、金边对比已增强，卡片落位后保留原图颜色。返回额外的 `plan`、`lastLand`、`poseAt(block,f)`、`blocks`。

```js
ZRFX.scanlineAssemble(tl, {
  container: document.getElementById('scan'), durationF: 120,
  boardRect: [288,160,1344,800], scanStartF: 8, scanEndF: 86,
  blocks: [
    {img:'assets/cards/scan_scene_title.png',slotRect:[69,30,1206,70.2],from:'left',landF:28,label:'场景标题'},
    {img:'assets/cards/scan_action.png',slotRect:[51,150,1242,144],from:'right',landF:52,label:'动作描述'},
    {img:'assets/cards/scan_dialogue.png',slotRect:[51,310,1242,459],from:'bottom',landF:78,label:'人物对白'}
  ]
});
```

与参考差异：蓝图配色改金色，落地页七区块改为可传入任意真实区块；三层低透明度位移残影替代 React `SpeedBlur`，按运动方向计算，贴合后的主图没有 blur。槽位说明、状态行等新增中文均不小于 40px。

## 历史实现验证与本次边界

任务 03 的历史检查为：代码经 Node 语法检查，模拟 DOM 对三个场景进行了共 723 个半帧状态采样，未出现 NaN 或 Infinity，前进、回退后再次取同帧的 DOM 状态一致，收束、分身出生、合体与区块落位锚点断言通过。模拟 DOM 仅验证状态与数学，不验证像素。作者未运行浏览器或渲染器，真实像素、字体度量、SVG 噪声和 3D 遮挡效果需由整体验证步骤确认；不能据此认定视觉通过。源参考及其许可为 Apache-2.0，来源提交为 `43bd349a136651865ecfa6ea1cf012f6e957d304`，文件头已记录原作者和修改性质。

# 任务 06 增量接口

以下均为可选参数；不传时保留任务 05 旧行为。实际六段源码位于 `../src/`，完整操作见 `../README.md`。

## fullScene

`ZRFX.fullScene(tl,root,globalOffset,durationF)` 返回 `{opts,L,audit,gate,cue,caption,camera,mask,chapter}`。`L` 将全片帧换为段内帧；helper 的时间参数使用全片帧，返回 audit 的组件时间使用段内帧。`cue` 支持 `sourceRectAt(localFrame)` 跟踪录屏滚动，再由 `camera.screenRect` 转为输出框。`end` 是动画退场末端，`cut` 是硬切帧；保持至硬切可将 `end` 设为 `cut+6`。章节外层按范围硬切，内部仍滚动上一章到新章。`caption` 用于故事板给定的底部说明，不经过 10 字指向框限制。

## filmCard

`ZRFX.filmCard(tl,{container,element,durationF,mode:'card'|'full',startF,landF,endF,pulseFrames,retreatF?,absorbStartF?,absorbEndF?,baseScale?})`。

- `element` 必须是源码中已声明源地址与时间窗的静音媒体；组件只移动其非定时外框，不改媒体入点或播放速度。
- `card`：原生内容 405×230，编码媒体宽 406px，最右补列由 405px 卡框裁出。`baseScale` 默认 2，所有脉冲最大 2.1；`landF` 结束推入，`retreatF` 开始 24 帧后退，吸入末端缩至极小。
- `full`：1920×1080 cover，使用 `assets/originals/` 真原片，时间参数保持相同。
- 暗角和颗粒使用素材上的静态 `data-color-grading`。默认 details 为 `vignette:.24,grain:.12,grainSize:.25,grainRoughness:.5`。须在源码写入标准属性供预编译发现，不用自绘噪声覆盖层。
- 返回 `{element,card,sampleAt,renderAt,proxy,mode,media,gradingDetails}`；`sampleAt(f)` 提供 scale、pulse、retreat、absorb 等离线审计值。

## basic3dScene / terminal3d

`basic3dScene` 新增 `labelSlam:true`：每站标签在落位帧全显并达到缩放峰；新增 `overview.textLandF` 指定总览文字完全落位帧。返回额外的 `labelSampleAt` 和 `overLabel`。

`terminal3d` 新增 `entryLandF`（首站推入结束）、`overview:{startF,landF,pose?}`（三窗拉远）、`dive:{startF,landF,station?,scale?}`（向当前末站冲入）。F3 使用 680、873、880 等全片锚点换算后的段内值。原飞行、打字和卡片原比例接口不变。

## clonerDepthEcho / cardFlockTumble

`clonerDepthEcho` 新增 `spawnPeaks` 数组：每个分身的主要出生变化在对应帧发生，之后 8 帧落稳。已有 `mergeF + mergeDurationF` 仍为精确合体帧。

`cardFlockTumble` 新增：`collapseDurationF` 默认 10（F6 为 11），`titlePeakF` 指定标题全显与砸入峰，`sloganLandF` 指定所有口号字完全落定，`entryPoses` 用三个 `{x,y,rx,ry,rz,s}` 替换三条飞行路径的首位置。位置相对 `center`，缩放相对 `cardSize`。返回新增 `title`、`characters`、`core`、`titleSampleAt`，方便离线验证。F6 使用全片 2106 闪核、2110 巨字、2154 起口号、2161 全落定，末帧保持显示。
