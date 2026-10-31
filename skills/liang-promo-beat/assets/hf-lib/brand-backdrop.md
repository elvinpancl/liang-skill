# 共用品牌背景与 logo 组合

`brand-backdrop.js` 在 `core.js`、`common.js` 之后加载，编译器自动包含。`build-frames.mjs` 每次从 `--accents` 指定的 accents.json 读取 `level: heavy`，将全片重拍帧号内嵌为 `FX.brandHeavyFrames`；运行时不请求网络。

```js
const background = FX.brandBackdrop(tl, {
  container, durationF: 222, fps: 30,
  frameOffset: 665, // 当前合成第 0 帧对应的全片帧
  impactFrames: [] // 可选的额外全片砸入帧
});
```

背景依次包含暖色径向渐变、顶部金色光晕、金色透视网格、暗角和 28 颗微尘。全部由当前帧计算；网格每帧向镜头推进 0.8 个世界坐标单位，每 280 单位重复。重拍提高网格和光晕亮度，6 帧内按平方曲线衰减，不增加全屏白色层。

`FX.brandGrid(parent)` 独立提供原 `terminal3d` 的 906 条网格线及原深度透明度公式。`grid.renderAt(globalFrame, projector, perspective, pulse)` 接受原 E3 的投影函数。E3 使用 `manualGrid:true`，在其相机采样后传入 `p => projectAt(p, camera)`，保持原透视几何、相机路径和卡片位置。其他场景使用默认的 2200px 透视、−3° 倾角。

`FX.brandLockup(tl, opts)` 提供透明背景的「logo、竖线、品牌中文名」组合（名称、logo、口号读 `FX.brand`），保留独立 `logoBox`、`divider`、`name`、`motto` 句柄。关键参数为 `startF`、`landF`、`dividerStartF/EndF`、`nameStartF/EndF`、`sweepStartF/EndF`、`sloganF/LandF`；全部是合成内帧。扫光裁切在 logo 内。片尾的绿环只扩散一次；末段呼吸缩放为 ±0.7%。

字体族来自品牌包：100–649 用中等字形，650–900 用重字形，由 `build-frames.mjs` 生成 `@font-face`。`FX.brandTextStyle(golden)` 返回参照 HTML 的白色或金色文字渐变。

## 剪映 v2 的说明区

保留区域为 x 360–1560、y 850–1010。

- E2：画廊中心 y 508 → 440；卡名顶部 y 870 → 746；取消会进入下方说明区的镜像卡片。
- E3：保留原布局，离线四角投影检查说明期间位于区域内的卡片底边约不超过 y 784。
- E4：内容整体缩为 84%，围绕 (960,540) 缩放，并上移 62px；背景保持全幅。静态剧本板底边 y 970 → 839.2。
- E5：内容整体缩为 82%，上移 55px；计数器顶部 y 900 → 760。主卡底边 y 955 → 825.3；背景保持全幅。
- E6：回顾编号标签保留 y 719，三张飞行卡改为 580×320，中心上移至 y 390；入口位姿补偿至原回顾卡中心，保持交接连续。品牌口号顶部 y 680，84px 字号，行高 1.15，底边约 y 777。

上述数值是布局和投影依据。Chrome 实际字体包围盒、裁切与透视投影以 `tools/audit-caption-zone.mjs` 的沙箱外报告为准，不把离线检查当作浏览器验收。
