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

参数：`img` 为主卡，`clones` 为分身图片数组，单项可为地址或 `{img,label}`；`spawnF:20`、`staggerF:2.2`、`spreadDurationF:20` 定义逐个排开；`mergeF:72`、`mergeDurationF:10` 定义全体同步吸回；`cardRect:[1090,350,690,390]`；`gapZ:250`、`dx:-58`、`dy:-6`、`perspective:1500`、`vanishingPoint:[360,120]` 控制纵队。`title:'从剧本到角色场景'`、`counterLabel:'内容资产'` 可替换。所有图使用 contain 保持原比例；已知素材按原生尺寸居中，分身可传 `nativeSize:[w,h]`，主卡可传顶层 `nativeSize`，不把小图撑满统一卡框。

帧语义：主卡从 0 帧升起，`spawnF` 前 8 帧按压，分身从主卡同一位置开始，以 `staggerF` 错峰飞向斜向纵深位置；最后分身到位之后才能设置 `mergeF`。合体帧 `mergedF = mergeF + mergeDurationF`，主卡单次弹跳与绿色边缘闪光同时触发，左下计数器保留总资产数并回弹。每一分身出生 2 帧后计数加一，5 帧滚动。返回额外的 `hero`、`clones`、`depthAt(f,index)`、`mergedF`，`index` 从 1 开始。

```js
ZRFX.clonerDepthEcho(tl, {
  container: document.getElementById('clone'), durationF: 120,
  img: 'assets/cards/clone_script.png',
  clones: ['clone_linyue','clone_chen','clone_wife','clone_scene_cabin','clone_scene_cloud'].map(name => 'assets/cards/'+name+'.png'),
  spawnF: 20, mergeF: 70
});
```

与参考差异：分身换成角色与场景真实素材，保留各图片信息，因此不褪成纯线框；分身不额外叠加失焦 blur，文字保持清晰。弹出使用一次有限过冲，代替 Remotion 的物理弹簧求解。计数器使用明确的上下位移和透明度，不加参考的数字模糊。

## scanlineAssemble

参数：`blocks:[{img,slotRect:[x,y,w,h],from,landF?,label?,rotation?}]` 必填，槽位使用画板内坐标。`from` 为相对槽位的 `[dx,dy]`、`{x,y,rotate}`，或 `'left'|'right'|'top'|'bottom'`，方向形式自动保证起点完全在画面外；所有图片 contain。`boardRect:[140,210,1640,720]` 是画板屏幕位置；`scanStartF:8`、`scanEndF:86` 定义扫描窗口；`flightF:14` 是每块提前起飞的时长。

帧语义：扫描线严格匀速，从画板 y=-20 到 y=height+20；默认落位帧由槽位下缘反算，按下缘排序后自动保留最少 4 帧间隔。显式 `landF` 完全按传入帧执行，可对齐重音；这时调用者负责协调扫描线与槽位下缘。全部区块必须在 `scanEndF` 前落位，否则抛出参数错误。落位前 `flightF` 帧起飞、一次轻微过冲，方向拖影由相邻帧位移差分计算，停稳后清零；落位后 1–14 帧显示四角咬合。返回额外的 `plan`、`lastLand`、`poseAt(block,f)`、`blocks`。

```js
ZRFX.scanlineAssemble(tl, {
  container: document.getElementById('scan'), durationF: 120,
  boardRect: [180,240,1560,680], scanStartF: 8, scanEndF: 86,
  blocks: [
    {img:'assets/cards/scan_scene_title.png',slotRect:[100,30,1360,130],from:'left',landF:28,label:'场景标题'},
    {img:'assets/cards/scan_action.png',slotRect:[100,200,1360,180],from:'right',landF:52,label:'动作描述'},
    {img:'assets/cards/scan_dialogue.png',slotRect:[100,430,1360,180],from:'bottom',landF:78,label:'人物对白'}
  ]
});
```

与参考差异：蓝图配色改金色，落地页七区块改为可传入任意真实区块；三层低透明度位移残影替代 React `SpeedBlur`，按运动方向计算，贴合后的主图没有 blur。槽位说明、状态行等新增中文均不小于 40px。

## 本次静态验证边界

代码经 Node 语法检查；模拟 DOM 对三个场景进行了共 723 个半帧状态采样，未出现 NaN 或 Infinity，前进、回退后再次取同帧的 DOM 状态一致，收束、分身出生、合体与区块落位锚点断言通过。模拟 DOM 仅验证状态与数学，不验证像素。作者未运行浏览器或渲染器，真实像素、字体度量、SVG 噪声和 3D 遮挡效果需由整体验证步骤确认；不能据此认定视觉通过。源参考及其许可为 Apache-2.0，来源提交为 `43bd349a136651865ecfa6ea1cf012f6e957d304`，文件头已记录原作者和修改性质。
