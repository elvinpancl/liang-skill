# 空间组件参数

这三个组件移植自 `参考_shotcraft/demos/`，来源提交为 `43bd349a136651865ecfa6ea1cf012f6e957d304`，原作者 Wei Yihao，Apache-2.0。加载顺序为 `core.js`、`common.js`、`brand-backdrop.js`、`scenes-spatial.js`。全部调用采用 `ZRFX.<name>(tl, opts)`；`tl` 是调用方的 GSAP 时间轴，`opts.container` 是当前段 DOM，`durationF` 是段总帧数，`fps` 默认 30。组件通过代理对象加入时间轴，独立返回 `renderAt(f)`；同一个输入帧可反向或重复调用。调用方负责在构建完成后注册时间轴。

所有时间均为段内帧号，允许小数帧。所有空间均为 1920×1080 坐标，`pose` 结构为 `{x,y,z,rx,ry,rz,s}`，角度为度、缩放默认 1。正变换和相机逆变换严格反序；不得把旋转顺序换掉。组件的所有中文原生 DOM 说明字均不少于 40px；截图中已有文字是原始素材内容，无法通过放大获得新细节。图片默认保持原比例且从不放大超过原生尺寸，给定素材名的原尺寸已内置，也可显式传 `nativeSize:[w,h]`。

## basic3dScene

参数：`stations:[{img,pose,label,nativeSize?,maxWidth?,maxHeight?,minWidth?,minHeight?}]`；`flights:[{from,to,startF,landF}]`，站点索引从 0 开始，飞行区间必须不重叠且前后相接；`overview:{startF,landF,scale,pose?,label?}` 可省略。`perspective` 默认 3000，`hop` 默认 0.3，`creep` 默认 0.015，`dustCount` 默认 60。默认截图最大显示范围为 1740×820，使用原图缩小装入卡框；小图以原像素居中，卡框最小 720×420。五站可分别提供不同宽高。总览未指定姿态时以站点包围范围的中心为中心，采用 `scale` 拉远。

帧语义：`startF` 从 `from` 站起飞，`landF` 精确对齐 `to` 站；飞行中以正弦包络拉远。停留期间缓推，并在下次起飞前恢复基准；因此精确落位帧不带额外缩放。总览期间所有卡片逐渐回到可见焦点。离焦卡透明度和 0–7px 景深只作用于单卡叶层，浮尘固定在世界坐标产生真实视差。返回 `{element,renderAt,sampleAt,cards,world,proxy}`；`sampleAt(f)` 返回相机姿态、站点进度和总览进度。

用法示例：`ZRFX.basic3dScene(tl,{container:stage,durationF:150,stations:[{img:'assets/cards/flight_story.png',label:'故事',pose:{x:0,y:0,z:0}},{img:'assets/cards/page_script.png',label:'剧本',pose:{x:2000,y:200,z:-500,ry:-28}}],flights:[{from:0,to:1,startF:36,landF:64}],overview:{startF:100,landF:130,scale:3,label:'从故事到成片'}})`。调整实际画面布局时优先修改 `pose` 与总览中心，保持逆变换数学不变。

## carousel3d

参数：`cards:[{img,label,nativeSize?}]`（也接受 `items`），字符串图片数组可用但不提供字幕。`stepLandF:[0,21,42,...]` 指定每次停靠的帧，默认均匀分配一整圈；第一项对应第 0 张卡，后续每项顺次前进一张，超过 N 后循环。`dwellF` 默认 5，最多占相邻停靠区间的 40%；`radius` 默认 690，`cardWidth` 默认 340，`cardHeight` 默认 460，`perspective` 默认 2200，`tilt` 默认 −9，`centerY` 默认 465，`push` 默认 34，`highlightAngle` 默认 26。素材尺寸为 206×190 时原像素居中，外围用原生 DOM 排编号及两行卡名。

帧语义：在每个 `stepLandF[k]`，第 `k % N` 张卡的方位角精确为 0；停靠后短暂停留，随后 smooth 曲线换位。为满足指定帧精确停靠，这里取消参考版的 50% 匀速底，保留环形公转、点亮、外推、字幕滚动。双面都用同一份内容，背面仅 `rotateY(180deg)`；正反面均有标准与 WebKit 背面隐藏。反射是以地面翻转的第二个完整 3D 环，8% 透明度与渐隐仅施加在面层。返回 `{element,renderAt,sampleAt,cards,reflections,ring,proxy}`；`sampleAt(f)` 含 `spin`、`selected`、`progress`。

用法示例：`ZRFX.carousel3d(tl,{container:stage,durationF:130,cards:styleCards,stepLandF:[0,16,32,48,64,80,96,112,128],dwellF:4})`。8 张卡配 9 个停靠帧可回到第一张卡；第一张与最后一张应使用相同正面位置检查双面、倒影与循环方向。

## terminal3d

参数：`windows:[{img,title,typeText,pose,nativeSize?,typeStartF?,typeEndF?,view?,width?,height?}]`，窗口默认 1120×500。`flights` 同 `basic3dScene`，也接受相邻站飞行的 `[[startF,landF],...]`；`typing:[[startF,endF],...]` 或 `[{startF,endF},...]` 可在顶层给定每窗打字区间，窗口自身参数优先。`perspective` 默认 2200，`tilt` 默认 −3，`viewAngles` 默认 `[8,-8,9]`，`pullPeak` 默认 1250。标题在顶部，逐字文案位于同一标题栏的第二行；下面居中放原生尺寸图片。

帧语义：每窗打字起点不得早于到站；默认在到站后 3 帧开始，以固定散列权重分配逐字时间，`typeEndF` 时完整显示。光标打字期间常亮，结束后按 8 帧半周期闪烁。窗间飞行中用 `sin(π·raw^0.85)×pullPeak` 拉远，拉远时景深变深，落位时当前窗滤镜清零。SVG 地面逐线投影与 CSS 相机逆变换同构，包括复合 X/Y/Z 旋转与缩放。默认保留小角度侧视；若需要严格正视原生像素验收，传 `tilt:0,viewAngles:[0,0,0]` 并选择开场推近结束后的停靠帧。返回 `{element,renderAt,sampleAt,projectAt,cards,world,typing,proxy}`。

用法示例：`ZRFX.terminal3d(tl,{container:stage,durationF:150,windows:[{img:'assets/cards/terminal_step01.png',title:'故事方向',typeText:'找到故事的方向'},{img:'assets/cards/terminal_step02.png',title:'剧情主线',typeText:'铺开剧情主线'},{img:'assets/cards/terminal_frozen.png',title:'规划冻结',typeText:'规划已冻结'}],flights:[[38,58],[90,110]],typing:[[8,25],[60,78],[113,129]]})`。原前两张仅 395×100、冻结卡 815×153，组件保留截图原细节，窗口标题负责大字讲清语义。

## 与参考的明确差异

色板统一为暖黑、金、品牌绿；真实截图代替参考手绘占位 UI。小图在大卡框内原像素呈现，未伪造高分辨率。轮播改成指定帧准确停靠，停留不叠匀速漂移；空间相机采用可复用的 smooth/inOut 缓动，未复刻参考里的自定义贝塞尔与时间子帧运动模糊。终端简化为真实截图与标题栏打字，未复制占位 CLI 输出、背光光池或结果状态。以上差异均不影响确定性寻帧、双面贴图与相机数学。
