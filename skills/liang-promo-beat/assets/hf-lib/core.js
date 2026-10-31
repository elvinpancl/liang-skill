/* FX core. Original deterministic DOM/GSAP support, 2026-10-21.
 * 品牌（颜色、字体、logo、名称、口号）读 window.FX_BRAND，由 build-frames.mjs 从品牌包生成并注入在本文件之前。
 * Pose mathematics adapted from shotcraft Basic3DScene.tsx (Apache-2.0),
 * commit 43bd349a136651865ecfa6ea1cf012f6e957d304, Copyright 2026 Wei Yihao.
 * Modified: reusable frame-local functions; no React or Remotion dependency. */
(function (global) {
  'use strict';
  const FX = global.ZRFX = global.ZRFX || {};
  const BRAND_DEFAULT = {colors:{bg:'#0b0a09',gold:'#e9b45a',hi:'#ffd98e',brand:'#5ad1ff',ink:'#f6f0e6',muted:'#a89e8f',dim:'#6d655a',warn:'#ff7a5c'},
    font:'sans-serif',logo:{src:'',width:780,height:396,alt:''},name:{zh:'',full:''},slogan:'',sloganSplit:0,wallText:''};
  const given = global.FX_BRAND || {};
  const B = FX.brand = {...BRAND_DEFAULT,...given,colors:{...BRAND_DEFAULT.colors,...(given.colors||{})},
    logo:{...BRAND_DEFAULT.logo,...(given.logo||{})},name:{...BRAND_DEFAULT.name,...(given.name||{})}};
  const rgbOf = hex => [1,3,5].map(i => parseInt(hex.slice(i,i+2),16)).join(',');
  // accent 默认等于品牌色；只在要复现旧画面时单独给
  B.rgb = {brand:rgbOf(B.colors.brand),accent:rgbOf(B.colors.accent||B.colors.brand)};
  B.fontStack = B.font + ', sans-serif';
  FX.clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
  FX.mix = (a, b, t) => a + (b - a) * t;
  FX.ease = {
    linear: t => t,
    smooth: t => t * t * (3 - 2 * t),
    out: t => 1 - Math.pow(1 - t, 3),
    inOut: t => t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t+2,3)/2,
    overshoot: t => 1 + 2.70158*Math.pow(t-1,3) + 1.70158*Math.pow(t-1,2)
  };
  FX.ramp = (f, startF, endF, ease = FX.ease.smooth) => {
    const t = endF <= startF ? Number(f >= endF) : FX.clamp((f-startF)/(endF-startF));
    return (typeof ease === 'function' ? ease : FX.ease[ease] || FX.ease.smooth)(t);
  };
  FX.el = (tag, cls, parent, style = {}) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    Object.assign(node.style, style);
    if (parent) parent.appendChild(node);
    return node;
  };
  FX.image = (src, parent, style = {}) => {
    const node = FX.el('img', 'fx-image', parent, {display:'block',objectFit:'contain',...style});
    node.src = src; node.alt = ''; node.draggable = false;
    return node;
  };
  FX.normalPose = p => ({x:0,y:0,z:0,rx:0,ry:0,rz:0,s:1,...p});
  FX.pose = pose => {
    const p=FX.normalPose(pose);
    return `translate3d(${p.x}px,${p.y}px,${p.z}px) rotateX(${p.rx}deg) rotateY(${p.ry}deg) rotateZ(${p.rz}deg) scale(${p.s})`;
  };
  FX.inversePose = pose => {
    const p=FX.normalPose(pose);
    return `scale(${1/p.s}) rotateZ(${-p.rz}deg) rotateY(${-p.ry}deg) rotateX(${-p.rx}deg) translate3d(${-p.x}px,${-p.y}px,${-p.z}px)`;
  };
  FX.drive = (tl, opts, renderAt) => {
    const fps = opts.fps || 30, durationF = opts.durationF;
    if (!Number.isFinite(durationF) || durationF <= 0) throw new Error('durationF must be positive');
    const state={f:0};
    renderAt(0);
    tl.fromTo(state,{f:0},{f:durationF,duration:durationF/fps,ease:'none',immediateRender:false,onUpdate:()=>{
      const frame=Math.round(state.f);
      renderAt(Math.abs(state.f-frame)<0.0001?frame:state.f);
    }},0);
    return state;
  };
  FX.colors = {bg:B.colors.bg,gold:B.colors.gold,highlight:B.colors.hi,green:B.colors.brand,text:B.colors.ink,muted:B.colors.muted,dim:B.colors.dim,warning:B.colors.warn};
})(window);
