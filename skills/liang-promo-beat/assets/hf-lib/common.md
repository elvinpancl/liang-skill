# 共用组件

加载顺序为 `core.js`、`common.js`。所有 API 都是 `ZRFX.<名称>(tl, opts)`，把确定性动画加入调用者的同一个暂停 GSAP 时间线，不创建或注册第二条合成时间线。共同参数为 `container`（本段 DOM 容器）、`durationF`（本段总帧数，必填）、`fps`（默认 `30`），所有 `*F`、关键帧 `f`、`renderAt(f)` 都使用段内帧号；允许小数帧。组件返回 `{element, renderAt, ...}`。`renderAt` 由输入帧完整重算其负责的样式，可正序、逆序或跳帧调用。

字体是品牌包的字体族（`FX.brand.font`），本地加载。源码不读取时钟、鼠标或上一帧，不使用无种子随机数。视频仍由 HyperFrames 的 `data-start`、`data-duration`、`data-media-start` 驱动，组件不操作播放头。默认视口为 `1920×1080`。挂载共享代码时须使用工程构建脚本内联到子合成 `<template>`，不能依赖子合成外的 `<head>`。

## camera：录屏运镜

参数：`element` 为源视频或图片 DOM；`keyframes:[{f,rect:[x,y,w,h],ease}]` 为源坐标裁切框；`sourceWidth/sourceHeight` 默认 `1920/1056`，`width/height` 默认 `1920/1080`。目标关键帧的 `ease` 控制从前一关键帧抵达该帧的插值，可使用 `smooth/out/linear/inOut`、GSAP 缓动字符串或纯函数。默认平滑插值。裁切框按等比铺满映射到视口，非 `16:9` 的框会按 cover 居中裁边，画面不拉伸。

帧语义：第一个关键帧之前保持首个裁切框，最后一个之后保持末个裁切框。返回 `punch(f,amount=0.08)` 在 `f` 达到冲击峰值，前 `2` 帧起势、后约 `17` 帧回弹；`shake(f,px=8)` 从 `f` 开始约 `12` 帧衰减震动。两者可多次调用，参数变化纳入同一个纯函数，注册后立即刷新当前帧，支持 0 帧冲击。`screenRect(srcRect,f)` 返回屏幕矩形 `[x,y,w,h]`，包括当帧的推近和震动；`matrixAt(f)` 返回 `{scale,x,y}`，`cropAt(f)` 返回插值后的源矩形。camera 只改变自己创建的非 timed 包装层，不改媒体时间参数。

用法：`const cam = ZRFX.camera(tl,{container:stage,element:video,durationF:120,keyframes:[{f:0,rect:[21.3333333333,0,1877.3333333333,1056]},{f:45,rect:[1040,560,880,495],ease:'out'}]}); cam.punch(55,.06).shake(55,5);`。需要贴住源图区域的说明框和隐私遮挡均传入同一个 `cam`，不要重复手算屏幕坐标。

## callout：指向说明

参数：`text` 为不超过 `10` 个字符的一行文字，空格及数字均计数；`camera` 与 `srcRect` 指定源图目标框。固定屏幕目标可省略 camera，使用 `rect`；动态自定义目标可传纯函数 `target(f)` 返回 `[x,y,w,h]`。`labelPos:[x,y]` 为文字框左上角，默认 `[140,820]`；`fontSize` 默认 `48` 且最小 `40`；`startF/endF` 为显示窗口，`zIndex` 默认 `20`。

帧语义：`startF` 开始四角从外扩 `26px` 咬进到 `8px`，约 `7` 帧完成；细连接线随后伸出，文字从第 `6` 帧开始按 `1.25` 帧错峰逐字升起。结束前 `5` 帧角标外退、文字快速收回，在 `endF` 完全隐藏。角标使用 scanline 参考的四个 `22px` L 角，源矩形位置每帧取自 `camera.screenRect`；连接线选择靠近文字的边界，不指向目标内部。

用法：`ZRFX.callout(tl,{container:stage,durationF:120,camera:cam,srcRect:[1264,967,312,76],text:'质量评分 94',labelPos:[330,550],startF:45,endF:113});`。返回额外 `label` 供调用者定位，但不建议让另一组件同时修改其 transform 或 opacity。

## chapterTag：章节标签

参数：`number` 默认 `'01'`、`title`、`position` 默认 `[80,72]`、`startF/endF`；`zIndex` 默认 `30`。标签使用 `58px` 数字及 `48px` 标题，数字为两位补零的垂直滚轮，标题从底部金线下升起。

帧语义：从 `startF` 起先亮出编号，数字约 `18` 帧滚动停靠；标题第 `7` 帧开始上升，约第 `23` 帧就位。结束前 `6` 帧向上退场。滚轮位置由当前帧直接计算，不根据上一次显示的数值推进。

用法：`ZRFX.chapterTag(tl,{container:stage,durationF:120,number:1,title:'写故事',startF:0,endF:115});`。

## textSlam：文字砸入

参数：`text`、`peakF`、`fontSize`（默认 `132`）、`color`（默认正文色）、`perChar`（默认否）、`staggerF`（逐字模式默认 `2`）、`attackF`（默认 `5`）、`shakePx`（默认 `6`）、`endF`。`shakeElement` 可指定底图层，与文字同步轻微震屏；未指定时只震动文字。也可传已有 `element`，由组件包装后施加整块冲击；已有元素模式不拆字。

帧语义：`peakF-attackF` 开始由 `1.25` 缩到 `1`，速度模糊在 `peakF` 清零，同帧达到金色泛光和轻震峰值，再作轻微回弹。逐字模式每个字的峰值为 `peakF+i*staggerF`。结束前 `5` 帧淡出。停留时文字完全清晰，泛光有界衰减。

用法：`ZRFX.textSlam(tl,{container:stage,durationF:120,text:'故事开始',peakF:18,fontSize:160,perChar:true,staggerF:2});`。较长文案需主动设置合适字号，保持主标题在安全区域内。

## flash：白闪或金闪

参数：`peakF`、`flashF`（默认 `5`，限制 `3–6` 帧）、`color`（`'white'`、`'gold'` 或 CSS 色值）、`opacity`（默认 `1`）、`zIndex`（默认 `90`）。这里 `durationF` 始终是段总帧数，闪光长度只由 `flashF` 控制。

帧语义：`peakF` 精确到达峰值，之后作归一化指数衰减，在 `peakF+flashF` 归零，之前不亮。它不会自行切换底层内容。

用法：`ZRFX.flash(tl,{container:stage,durationF:120,peakF:60,flashF:4,color:'gold'});`。

## crashZoom：冲击推近转场

参数：`a/b` 为先后两层 DOM，`peakF` 为闪白切层帧；`point:[x,y]` 默认画面中心，`scale` 默认 `3.4`；`attackF` 默认 `8`，`settleF` 默认 `12`；`flashF` 默认 `4`，`flashColor` 默认白色。组件为两层创建独立非 timed 包装层，避免覆盖内部组件运镜。

帧语义：从 `peakF-attackF` 起按指数加速向 `point` 推近，模糊依据纯函数中心差分速度生成；`peakF` 隐藏 A、显示 B，并白闪；B 从 `1.07` 回弹到 `1`。峰帧后 A 不会再显示，B 保持清晰。返回额外 `{a,b,flash}`。

用法：`ZRFX.crashZoom(tl,{container:stage,durationF:120,a:layerA,b:layerB,peakF:60,point:[1370,650],scale:3});`。不要同时对相同 A/B 包装层应用其他控制 opacity 或 transform 的组件。

## whip：甩镜转场

参数：`a/b`、`peakF`、`direction`（默认 `'left'`，另支持 `right/up/down`）、`halfF`（峰前与峰后各 `6` 帧）、`blurPx`（峰值默认 `32`）。横向用 SVG 高斯模糊 `stdDeviation="x 0"`，纵向用 `"0 y"`，是沿运动方向的拖影。

帧语义：从 `peakF-halfF` 到 `peakF+halfF`，A 移出、B 从相反侧同步移入；在 `peakF` 双层恰好半程，速度与方向模糊达到峰值。结束时 A 隐藏、B 精确归零位移，滤镜移除。返回额外 `{a,b}`。SVG 标识由容器名加共享确定性构建计数生成，多段内联不会重名。

用法：`ZRFX.whip(tl,{container:stage,durationF:120,a:layerA,b:layerB,peakF:60,direction:'left',halfF:6});`。

## chromaticSplit：RGB 通道分离

参数：`element` 为要分离的实际内容 DOM，也接受 `target` 别名；`peakF`、`amount`（峰值偏移默认 `24px`）、`riseF`（默认 `2`）、`decayF`（默认 `14`）。组件在独立包装层上将实际内容分成红绿蓝三通道，以相反偏移合成，不用装饰边框模拟，不复制或驱动视频播放头。

帧语义：`peakF-riseF` 开始，`peakF` 偏移最大，之后指数衰减，在 `peakF+decayF` 恢复中性并去除滤镜。全部通道偏移每帧重算；多个合成的 SVG id 互不冲突。

用法：`ZRFX.chromaticSplit(tl,{container:stage,durationF:120,element:heroLayer,peakF:70,amount:28,decayF:12});`。

## mask：敏感区域跟随打码

参数：`camera`、`srcRect`（或固定屏幕 `rect`）、`startF/endF`、`padding`（默认 `5px` 安全外扩）、`blurPx`（默认 `32px`，最小 `24px`）、`darkness`（默认 `0.86`）、`zIndex`（默认 `15`）。使用真正的背景模糊 `backdrop-filter` 配合暖黑暗块；字体、图片等被遮挡内容的原件不改动。

帧语义：在 `[startF,endF)` 全程立即覆盖，不作可能泄露原文的入退场淡化。位置、尺寸每帧由 `camera.screenRect` 计算，同步包含推近与震动；安全外扩在屏幕像素坐标中执行。不能把遮挡层放进 camera 已经变换的源层，否则会二次变换。此实现依赖系统 Chrome 的 `backdrop-filter` 支持，实际覆盖范围需通过渲染逐帧核验。

用法：`ZRFX.mask(tl,{container:stage,durationF:120,camera:cam,srcRect:[160,44,1604,40]});`。多个敏感矩形分别调用，多层遮挡均应位于源画面上方、字幕与说明框下方。

## 参考差异与验证边界

共用组件的颜色和字体都来自品牌包（`FX.brand`）。计数和文字配方中的历史值判断、全局 selector、相对累计位移均已改为帧的纯函数。白闪由原配方的硬亮灭改为 `3–6` 帧指数衰减；甩镜增加单轴拖影；RGB 改为处理实际内容的通道滤镜。camera 的取景和隐私遮罩为本项目新增数学映射。动画端点、确定性以及 SVG 通道数可静态或以 DOM 状态验证；像素、真实 Chrome 模糊及视频提取效果仍以测试片渲染证据为准。
