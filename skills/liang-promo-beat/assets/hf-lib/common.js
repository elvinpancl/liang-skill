/*
 * Common motion components. Frame-local, deterministic, GSAP-seekable.
 * Adapted motion recipes: ~/.claude/skills/music-to-video/references/motion-primitives/
 * crash-zoom-in, hypercut-whip, flash-cut, chromatic-split, screen-shake,
 * mask-reveal, counting-punch, braam-punch, kinetic-letter-in, slot-machine-reveal.
 * L-corner geometry adapted from video-shotcraft, Apache-2.0,
 * demos/effects/scanline-assemble-flyin/ScanlineAssembleFlyin.tsx,
 * commit 43bd349a136651865ecfa6ea1cf012f6e957d304. Original license retained in
 * LICENSE-shotcraft. Copyright 2026 Wei Yihao. Modified 2026-10-21. Only visual mathematics is ported; no React runtime.
 */
(function (FX) {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const C = { bg: FX.brand.colors.bg, gold: FX.brand.colors.gold, light: FX.brand.colors.hi, green: FX.brand.colors.brand, ink: FX.brand.colors.ink, dim: FX.brand.colors.muted };
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const mix = (a, b, t) => a + (b - a) * t;
  const out = (t) => 1 - Math.pow(1 - clamp(t), 3);
  const smooth = (t) => { const p = clamp(t); return p * p * (3 - 2 * p); };
  const ramp = (f, a, b, ease = smooth) => ease(clamp((f - a) / Math.max(0.000001, b - a)));
  const px = (n) => Number(n.toFixed(5)) + 'px';
  const alpha = (n) => String(clamp(n));
  const E = (tag, cls, parent, style = {}) => FX.el(tag, cls, parent, style);
  const own = (o, key, value) => Object.prototype.hasOwnProperty.call(o, key) ? o[key] : value;
  const uid = (opts, kind) => {
    FX._commonIds = (FX._commonIds || 0) + 1;
    return (opts.id || opts.container.id || 'zrfx') + '-' + kind + '-' + FX._commonIds;
  };
  function svg(tag, parent, attrs) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, String(v)));
    if (parent) parent.appendChild(node);
    return node;
  }
  function full(parent, cls, extra = {}) {
    return E('div', cls, parent, Object.assign({ position: 'absolute', inset: '0', width: '1920px', height: '1080px', pointerEvents: 'none', boxSizing: 'border-box' }, extra));
  }
  function wrap(target, cls, container) {
    if (!target) throw new Error(cls + ': missing element');
    const parent = target.parentNode || container;
    const layer = E('div', cls, null, { position: 'absolute', inset: '0', width: '1920px', height: '1080px', transformOrigin: '0 0', pointerEvents: 'none' });
    if (target.parentNode) parent.insertBefore(layer, target);
    else parent.appendChild(layer);
    layer.appendChild(target);
    layer.setAttribute('data-layout-allow-overflow','true'); // Intentional crop / transition travel.
    return layer;
  }
  function finish(tl, opts, element, renderAt, extras = {}) {
    FX.drive(tl, opts, renderAt);
    return Object.assign({ element, renderAt }, extras);
  }
  function rect(r) {
    if (Array.isArray(r)) return r.map(Number);
    if (r && typeof r === 'object') return [r.x, r.y, r.w == null ? r.width : r.w, r.h == null ? r.height : r.h].map(Number);
    throw new Error('Expected rect [x,y,w,h]');
  }
  function easeFunction(e) {
    if (typeof e === 'function') return e;
    if (e && FX.ease && FX.ease[e]) return FX.ease[e];
    if (e && typeof gsap.parseEase === 'function') return gsap.parseEase(e);
    return smooth;
  }
  function pulse(f, peakF, decayF = 14, riseF = 2) {
    if (f < peakF - riseF || f >= peakF + decayF) return 0;
    if (f === peakF) return 1;
    if (f <= peakF) return ramp(f, peakF - riseF, peakF, out);
    const p = (f - peakF) / decayF;
    return (Math.exp(-5 * p) - Math.exp(-5)) / (1 - Math.exp(-5));
  }
  function shakeAt(f, peakF, amount) {
    const p = f - peakF;
    if (p < 0 || p >= 12) return [0, 0];
    const q = p / 12;
    return [amount * Math.cos(p * Math.PI * 0.91) * Math.pow(1 - q, 2), amount * 0.57 * Math.cos(p * Math.PI * 1.37) * Math.pow(1 - q, 2)];
  }
  function life(f, startF, endF, enterF = 5, exitF = 5) {
    return ramp(f, startF, startF + enterF, out) * (1 - ramp(f, endF - exitF, endF, out));
  }
  // D[f] measures the change from f-1 to f. Put the dominant attack in that
  // interval, not at the start of an ease-out or at a continuous midpoint.
  function impactAttack(f, peak, attack = 5) {
    if (f < peak - 1) return 0.12 * ramp(f, peak - Math.max(2, attack), peak - 1);
    return mix(0.12, 1, ramp(f, peak - 1, peak, t => t));
  }
  const calloutScopes = new WeakMap();

  // Crop-to-cover: image-space rectangle center maps to the viewport center.
  // The same affine matrix is used for the actual source and screenRect().
  FX.camera = function (tl, opts) {
    const source = opts.element;
    const vw = opts.width || 1920, vh = opts.height || 1080;
    const sw = opts.sourceWidth || 1920, sh = opts.sourceHeight || 1056;
    const keys = (opts.keyframes || [{ f: 0, rect: [0, 0, sw, sh] }])
      .map(k => ({ f: Number(k.f), rect: rect(k.rect), ease: k.ease })).sort((a, b) => a.f - b.f);
    if (!keys.length || keys.some(k => !Number.isFinite(k.f) || k.rect.some(v => !Number.isFinite(v)) || k.rect[2] <= 0 || k.rect[3] <= 0)) throw new Error('camera: invalid keyframes');
    const layer = wrap(source, 'zr-camera-source', opts.container);
    Object.assign(layer.style, { width: px(sw), height: px(sh), willChange: 'transform' });
    Object.assign(source.style, { position: 'absolute', left: '0', top: '0', width: px(sw), height: px(sh), maxWidth: 'none', maxHeight: 'none', objectFit: 'fill' });
    const punches = [], shakes = [];
    let currentF = 0;
    function cropAt(f) {
      if (f <= keys[0].f) return keys[0].rect.slice();
      for (let i = 1; i < keys.length; i++) {
        if (f <= keys[i].f) {
          const p = ramp(f, keys[i - 1].f, keys[i].f, easeFunction(keys[i].ease));
          return keys[i].rect.map((v, j) => mix(keys[i - 1].rect[j], v, p));
        }
      }
      return keys[keys.length - 1].rect.slice();
    }
    function matrixAt(f) {
      const r = cropAt(f);
      let zoom = 1, dx = 0, dy = 0;
      punches.forEach(p => {
        const q = f - p.f;
        zoom += p.amount * pulse(f, p.f, 17, 2);
        if (q > 1 && q < 17) zoom -= p.amount * 0.16 * Math.sin(Math.PI * clamp((q - 1) / 16)) * Math.exp(-(q - 1) / 7);
      });
      shakes.forEach(s => { const d = shakeAt(f, s.f, s.px); dx += d[0]; dy += d[1]; });
      const scale = Math.max(vw / r[2], vh / r[3]) * zoom;
      return { scale, x: vw / 2 - (r[0] + r[2] / 2) * scale + dx, y: vh / 2 - (r[1] + r[3] / 2) * scale + dy };
    }
    function screenRect(srcRect, f) {
      const r = rect(srcRect), m = matrixAt(f);
      return [r[0] * m.scale + m.x, r[1] * m.scale + m.y, r[2] * m.scale, r[3] * m.scale];
    }
    const renderAt = f => {
      currentF = f;
      const m = matrixAt(f);
      layer.style.transform = `matrix(${m.scale},0,0,${m.scale},${m.x},${m.y})`;
    };
    const handle = finish(tl, opts, layer, renderAt, {
      source, matrixAt, cropAt, screenRect,
      punch(f, amount = 0.08) { punches.push({ f: Number(f), amount: Number(amount) }); renderAt(currentF); return handle; },
      shake(f, amount = 8) { shakes.push({ f: Number(f), px: Number(amount) }); renderAt(currentF); return handle; }
    });
    return handle;
  };

  FX.callout = function (tl, opts) {
    const chars = Array.from(String(opts.text || ''));
    if (chars.filter(c => !/\s/.test(c)).length > 10) throw new Error('callout: text must contain no more than 10 non-space characters');
    const start = opts.startF || 0, end = own(opts, 'endF', opts.durationF);
    const exitF = clamp(own(opts, 'exitF', 7), 6, 8), enterF = Math.max(0, own(opts, 'enterF', 7));
    const revealF = opts.revealF;
    const scope = opts.scope || opts.container.closest('[data-composition-id]') || opts.container;
    const siblings = calloutScopes.get(scope) || [];
    const entry = {start, end, order:siblings.length};
    siblings.push(entry); calloutScopes.set(scope, siblings);
    const layer = full(opts.container, 'zr-callout', { zIndex: String(opts.zIndex || 20) });
    const drawing = svg('svg', layer, { width: 1920, height: 1080, viewBox: '0 0 1920 1080', 'aria-hidden': 'true' });
    Object.assign(drawing.style, { position: 'absolute', inset: '0', overflow: 'visible' });
    const corners = svg('path', drawing, { fill: 'none', stroke: C.light, 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    const connector = svg('path', drawing, { fill: 'none', stroke: C.gold, 'stroke-width': 2 });
    const pos = opts.labelPos || [140, 820];
    const fs = Math.max(40, opts.fontSize || 48), boxW = chars.length * fs + 40, boxH = fs + 32;
    const label = E('div', 'zr-callout-label', layer, { position: 'absolute', left: px(pos[0]), top: px(pos[1]), width: px(boxW), height: px(boxH), display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', background: 'rgba(11,10,9,.92)', color: C.ink, fontFamily: FX.brand.fontStack, fontSize: px(fs), lineHeight: '1.2', whiteSpace: 'nowrap', boxSizing: 'border-box', borderBottom: '2px solid ' + C.gold });
    const letters = chars.map(c => { const e = E('span', 'zr-callout-char', label, { display: 'inline-block', minWidth: c === ' ' ? '0.35em' : '0', willChange: 'transform,opacity' }); e.textContent = c === ' ' ? '\u00a0' : c; return e; });
    function renderAt(f) {
      entry.currentF = f;
      // End the old cue before the next starts, with a 6–8f retirement. The
      // schedule is declarative and independent of construction/seek order.
      const next = siblings.filter(s => s.start > start || (s.start === start && s.order > entry.order));
      const stop = Math.min(end, ...next.map(s => s.start));
      const cut = Math.min(own(opts,'cutF',Infinity), own(opts,'targetEndF',Infinity));
      const enter = enterF === 0 ? Number(f >= start) : ramp(f, start, start + enterF, out);
      const leave = ramp(f, stop - exitF, stop, out);
      const target = typeof opts.target === 'function' ? opts.target(f) : opts.camera ? opts.camera.screenRect(opts.srcRect || opts.rect, f) : rect(opts.rect || opts.srcRect);
      const [x, y, w, h] = target || [0,0,0,0];
      const visible = w > 0 && h > 0 && x < 1920 && y < 1080 && x + w > 0 && y + h > 0;
      const active = visible && f >= start && f < stop && f < cut && (!opts.targetVisible || opts.targetVisible(f));
      layer.style.opacity = active ? '1' : '0';
      const gap = mix(26, 8, enter) + 25 * leave, arm = 22 * (1 - leave);
      corners.setAttribute('d', `M${x-gap} ${y-gap+arm}V${y-gap}H${x-gap+arm}M${x+w+gap-arm} ${y-gap}H${x+w+gap}V${y-gap+arm}M${x+w+gap} ${y+h+gap-arm}V${y+h+gap}H${x+w+gap-arm}M${x-gap+arm} ${y+h+gap}H${x-gap}V${y+h+gap-arm}`);
      corners.style.opacity = alpha(enter * (1 - leave));
      const cx = x + w / 2, cy = y + h / 2, lx = pos[0] + boxW / 2, ly = pos[1] + boxH / 2;
      const horizontal = Math.abs(lx - cx) / Math.max(1, w) > Math.abs(ly - cy) / Math.max(1, h);
      const ax = horizontal ? (lx < cx ? x - gap : x + w + gap) : cx;
      const ay = horizontal ? cy : (ly < cy ? y - gap : y + h + gap);
      const bx = horizontal ? (lx < cx ? pos[0] + boxW : pos[0]) : lx;
      const by = horizontal ? ly : (ly < cy ? pos[1] + boxH : pos[1]);
      const mx = horizontal ? (ax + bx) / 2 : bx, my = horizontal ? ay : (ay + by) / 2;
      const d = `M${ax} ${ay}L${mx} ${my}L${bx} ${by}`;
      const length = Math.hypot(mx - ax, my - ay) + Math.hypot(bx - mx, by - my);
      connector.setAttribute('d', d);
      connector.setAttribute('stroke-dasharray', String(length));
      const lineP = revealF == null ? ramp(f, start + 5, start + 12, out) : revealF === 0 ? Number(f >= start) : ramp(f, start, start + revealF, out);
      connector.setAttribute('stroke-dashoffset', String(length * (1 - lineP)));
      connector.style.opacity = alpha(enter * (1 - leave));
      const labelP = revealF == null ? ramp(f, start + 6, start + 9, out) : lineP;
      label.style.opacity = alpha(labelP * (1 - leave));
      label.style.transform = `translateY(${px(-14 * leave)})`;
      letters.forEach((e, i) => {
        const p = revealF == null ? ramp(f, start + 6 + i * 1.25, start + 15 + i * 1.25, out)
          : revealF === 0 ? Number(f >= start) : ramp(f, start + revealF * 0.35 * i / Math.max(1,chars.length - 1), start + revealF, out);
        e.style.transform = `translateY(${px((1 - p) * (fs + 10) - 12 * leave)})`;
        e.style.opacity = alpha(p * (1 - leave));
      });
    }
    entry.renderAt = renderAt;
    const handle = finish(tl, opts, layer, renderAt, { label, scope });
    // A new cue can truncate an already-built cue at frame zero. Refresh only
    // at registration so the first rendered state equals a later seek to zero.
    siblings.forEach(s => {if (s !== entry && s.renderAt) s.renderAt(s.currentF);});
    return handle;
  };

  FX.chapterTag = function (tl, opts) {
    const start = opts.startF || 0, end = own(opts, 'endF', opts.durationF);
    const title = String(opts.title || ''), number = String(own(opts, 'number', '01')).padStart(2, '0');
    const previous = String(own(opts, 'previousNumber', Math.max(0, Number(number) - 1))).padStart(number.length, '0');
    const position = opts.position || [80, 72], digitH = 74;
    const layer = E('div', 'zr-chapter-tag', opts.container, { position: 'absolute', left: px(position[0]), top: px(position[1]), display: 'flex', alignItems: 'center', gap: '24px', height: '82px', color: C.ink, fontFamily: FX.brand.fontStack, zIndex: String(opts.zIndex || 30), pointerEvents: 'none' });
    const digits = E('div', 'zr-chapter-number', layer, { display: 'flex', height: px(digitH), overflow: 'hidden', color: C.gold, fontSize: '58px', lineHeight: px(digitH), fontVariantNumeric: 'tabular-nums' });
    // Roll the complete number together: 09 -> 10 never exposes 00, 19 or 78.
    const crop = E('div', 'zr-number-crop', digits, { width: px(number.length * 44), height: px(digitH), overflow:'hidden' });
    crop.setAttribute('data-layout-ignore','true'); // Only the rolling number mask, never the title.
    const reel = E('div', 'zr-number-reel', crop, {width:'100%',willChange:'transform'});
    for (const value of [previous,number]) {
      const cell = E('div','zr-number-cell',reel,{height:px(digitH),lineHeight:px(digitH),textAlign:'center',letterSpacing:'4px'});
      cell.textContent = value;
    }
    const textCrop = E('div', 'zr-chapter-title-crop', layer, { height: '80px', overflow: 'hidden', position: 'relative', padding: '0 2px', minWidth: px(Math.max(120, Array.from(title).length * 50)) });
    const text = E('div', 'zr-chapter-title', textCrop, { fontSize: '48px', lineHeight: '76px', whiteSpace: 'nowrap', willChange: 'transform' });
    text.textContent = title;
    const line = E('div', 'zr-chapter-line', textCrop, { position: 'absolute', left: '0', right: '0', bottom: '0', height: '3px', background: C.gold, transformOrigin: 'left center' });
    function renderAt(f) {
      const enter = ramp(f, start, start + 5, out), leave = ramp(f, end - 6, end, out);
      layer.style.opacity = alpha(enter * (1 - leave));
      layer.style.transform = `translateY(${px(-22 * leave)})`;
      reel.style.transform = `translateY(${px(-digitH * ramp(f, start, start + 18, out))})`;
      text.style.transform = `translateY(${px(84 * (1 - ramp(f, start + 7, start + 23, out)))})`;
      line.style.transform = `scaleX(${ramp(f, start + 2, start + 14, out) * (1 - leave)})`;
    }
    return finish(tl, opts, layer, renderAt, {number, previousNumber:previous});
  };

  FX.textSlam = function (tl, opts) {
    const peak = opts.peakF || 0, end = own(opts, 'endF', opts.durationF);
    const layer = opts.element ? wrap(opts.element, 'zr-text-slam-layer', opts.container) : full(opts.container, 'zr-text-slam-layer', { display: 'flex', alignItems: 'center', justifyContent: 'center' });
    const content = opts.element || E('div', 'zr-text-slam', layer, { color: opts.color || C.ink, fontFamily: FX.brand.fontStack, fontSize: px(opts.fontSize || 132), lineHeight: '1.2', whiteSpace: 'nowrap', textAlign: 'center', maxWidth: '1740px', transformOrigin: '50% 50%', willChange: 'transform,filter' });
    const shakeLayer = opts.shakeElement ? wrap(opts.shakeElement, 'zr-text-slam-shake', opts.container) : null;
    const chars = Array.from(String(opts.text || ''));
    let letters;
    if (!opts.element && opts.perChar) {
      letters = chars.map(c => { const e = E('span', 'zr-slam-char', content, { display: 'inline-block', transformOrigin: '50% 70%' }); e.textContent = c === ' ' ? '\u00a0' : c; return e; });
    } else {
      if (!opts.element) content.textContent = String(opts.text || '');
      letters = [content];
    }
    const anticipation = opts.perChar ? (letters.length - 1) * (opts.staggerF || 2) : 0;
    const start = peak - (opts.attackF || 5) - anticipation;
    function renderAt(f) {
      const leave = 1 - ramp(f, end - 5, end, out), sh = shakeAt(f, peak, opts.shakePx == null ? 6 : opts.shakePx);
      layer.style.opacity = alpha(f >= start ? leave : 0);
      layer.style.transform = `translate(${px(sh[0])},${px(sh[1])})`;
      if (shakeLayer) shakeLayer.style.transform = `translate(${px(sh[0])},${px(sh[1])})`;
      letters.forEach((e, i) => {
        // Stagger only anticipation; the complete title strikes on peakF.
        const attack = (opts.attackF || 5) + (opts.perChar ? (letters.length - 1 - i) * (opts.staggerF || 2) : 0);
        const p = impactAttack(f, peak, attack), q = f - peak;
        const settle = q > 0 && q < 16 ? -0.022 * Math.sin(q * Math.PI / 5) * Math.exp(-q / 5) : 0;
        const hit = f < peak ? p * 0.2 : pulse(f, peak, 18, 0);
        e.style.transform = `scale(${1 + 0.25 * (1 - p) + settle})`;
        e.style.filter = `blur(${px(20 * (1 - p))})`;
        e.style.opacity = alpha(p);
        e.style.textShadow = `0 0 ${px(44 * hit)} rgba(233,180,90,${0.82 * hit})`;
      });
    }
    return finish(tl, opts, layer, renderAt, { content });
  };

  FX.flash = function (tl, opts) {
    const peak = opts.peakF || 0, span = clamp(opts.flashF || 4, 3, 5);
    const color = opts.color === 'gold' ? C.light : opts.color === 'white' || !opts.color ? '#ffffff' : opts.color;
    const background = opts.color === 'gold'
      ? 'radial-gradient(ellipse 68% 65% at 50% 50%,#ffffff 0%,rgba(255,255,248,.98) 10%,rgba(255,238,190,.82) 26%,rgba(255,210,116,.45) 44%,rgba(233,180,90,.12) 61%,transparent 78%)'
      : color;
    const layer = full(opts.container, 'zr-flash', { background, zIndex: String(opts.zIndex || 90), opacity: '0' });
    function renderAt(f) {
      const p = (f - peak) / span;
      const o = p >= 0 && p < 1 ? (Math.exp(-5 * p) - Math.exp(-5)) / (1 - Math.exp(-5)) : 0;
      layer.style.opacity = alpha(o * own(opts, 'opacity', 1));
    }
    return finish(tl, opts, layer, renderAt, {peakF:peak,decayF:span});
  };

  // A narrow diagonal highlight crosses the screen; the rest stays transparent.
  FX.goldSweep = function (tl, opts) {
    const peak=opts.peakF || 0, span=clamp(opts.decayF || 4,3,5);
    const layer=full(opts.container,'zr-gold-sweep',{overflow:'hidden',zIndex:String(opts.zIndex || 90)});
    const band=E('div','zr-gold-sweep-band',layer,{position:'absolute',left:'-75px',top:'-360px',width:'150px',height:'1800px',transformOrigin:'50% 50%',background:'linear-gradient(90deg,transparent,rgba(233,180,90,.12) 18%,rgba(255,219,147,.75) 40%,#ffffff 50%,rgba(255,237,192,.88) 57%,rgba(233,180,90,.12) 82%,transparent)'});
    function sampleAt(f) {
      const age=f-peak, p=age/span;
      return {x:age<0?mix(-420,960,clamp(age+1)):960+1560*p,
        opacity:age>=0&&age<span?(Math.exp(-5*p)-Math.exp(-5))/(1-Math.exp(-5)):age>=-1&&age<0?.08*clamp(age+1):0};
    }
    function renderAt(f){const s=sampleAt(f);layer.style.opacity=alpha(s.opacity);band.style.transform=`translateX(${px(s.x)}) rotate(24deg)`;}
    return finish(tl,opts,layer,renderAt,{band,sampleAt,peakF:peak,decayF:span});
  };

  FX.crashZoom = function (tl, opts) {
    const peak = opts.peakF || 0, attack = opts.attackF || 8, settle = opts.settleF || 12;
    const point = opts.point || [960, 540], scale = opts.scale || 3.4;
    const a = wrap(opts.a, 'zr-crash-a', opts.container), b = wrap(opts.b, 'zr-crash-b', opts.container);
    const flash = FX.flash(tl, Object.assign({}, opts, { peakF: peak, flashF: opts.flashF || 4, color: opts.flashColor || 'white' }));
    const at = f => {
      const p = clamp((f - (peak - attack)) / attack), e = p === 0 ? 0 : Math.pow(2, 10 * (p - 1));
      return mix(1, scale, e);
    };
    function renderAt(f) {
      const s = at(f), blur = f < peak ? Math.min(20, Math.abs(at(f + 0.5) - at(f - 0.5)) * 30) : 0;
      a.style.transform = `translate(${px(point[0] * (1 - s))},${px(point[1] * (1 - s))}) scale(${s})`;
      a.style.opacity = f < peak ? '1' : '0';
      a.style.filter = `blur(${px(blur)})`;
      const n = 1 + 0.07 * (1 - ramp(f, peak, peak + settle, out));
      b.style.transform = `translate(${px(960 * (1 - n))},${px(540 * (1 - n))}) scale(${n})`;
      b.style.opacity = f >= peak ? '1' : '0';
      b.style.filter = 'none';
      flash.renderAt(f);
    }
    return finish(tl, opts, a, renderAt, { a, b, flash });
  };

  function directionalFilter(opts, kind, horizontal) {
    const id = uid(opts, kind);
    const root = svg('svg', opts.container, { width: 0, height: 0, 'aria-hidden': 'true' });
    Object.assign(root.style, { position: 'absolute', pointerEvents: 'none' });
    const defs = svg('defs', root), filter = svg('filter', defs, { id, x: '-30%', y: '-30%', width: '160%', height: '160%', 'color-interpolation-filters': 'sRGB' });
    const gaussian = svg('feGaussianBlur', filter, { in: 'SourceGraphic', stdDeviation: '0 0', edgeMode: 'duplicate' });
    return { id, root, render(value) { gaussian.setAttribute('stdDeviation', horizontal ? `${value} 0` : `0 ${value}`); } };
  }
  FX.whip = function (tl, opts) {
    const peak = opts.peakF || 0, attack = opts.attackF ?? 4, settle = opts.settleF ?? 5, dir = opts.direction || 'left';
    const horizontal = dir === 'left' || dir === 'right', sign = dir === 'left' || dir === 'up' ? -1 : 1, distance = horizontal ? 1920 : 1080;
    const a = wrap(opts.a, 'zr-whip-a', opts.container), b = wrap(opts.b, 'zr-whip-b', opts.container);
    const fa = directionalFilter(opts, 'whip-a', horizontal), fb = directionalFilter(opts, 'whip-b', horizontal);
    function sampleAt(f) {
      const exit=clamp((f-(peak-attack))/attack), enter=clamp((f-peak)/settle);
      const outgoing=distance*sign*Math.pow(exit,3);
      const incoming=-sign*(opts.entryDistance ?? 240)*Math.pow(1-enter,3);
      const blur=f<peak?(opts.blurPx || 42)*exit*exit:(opts.blurPx || 42)*Math.pow(1-enter,3);
      return {progress:f<peak?exit:1,displacement:outgoing,incoming,blur,
        outgoingOpacity:Number(f<peak),incomingOpacity:Number(f>=peak)};
    }
    function renderAt(f) {
      const {displacement:x,incoming,blur:strength,outgoingOpacity,incomingOpacity} = sampleAt(f);
      a.style.transform = horizontal ? `translateX(${px(x)})` : `translateY(${px(x)})`;
      b.style.transform = horizontal ? `translateX(${px(incoming)})` : `translateY(${px(incoming)})`;
      a.style.opacity = String(outgoingOpacity);
      b.style.opacity = String(incomingOpacity);
      a.style.filter = strength > 0.001 ? `url(#${fa.id})` : 'none';
      b.style.filter = strength > 0.001 ? `url(#${fb.id})` : 'none';
      fa.render(strength); fb.render(strength);
    }
    return finish(tl, opts, a, renderAt, { a, b, sampleAt,peakF:peak,attackF:attack,settleF:settle,direction:dir });
  };

  FX.chromaticSplit = function (tl, opts) {
    const layer = wrap(opts.element || opts.target, 'zr-chromatic', opts.container);
    const id = uid(opts, 'rgb'), peak = opts.peakF || 0, amount = opts.amount || 24, decay = opts.decayF || 14;
    const root = svg('svg', opts.container, { width: 0, height: 0, 'aria-hidden': 'true' });
    Object.assign(root.style, { position: 'absolute', pointerEvents: 'none' });
    const defs = svg('defs', root), filter = svg('filter', defs, { id, x: '-15%', y: '-15%', width: '130%', height: '130%', 'color-interpolation-filters': 'sRGB' });
    const matrices = [
      '1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0',
      '0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0',
      '0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0'
    ];
    const offsets = matrices.map((values, i) => {
      svg('feColorMatrix', filter, { in: 'SourceGraphic', type: 'matrix', values, result: 'channel' + i });
      return svg('feOffset', filter, { in: 'channel' + i, dx: 0, dy: 0, result: 'offset' + i });
    });
    svg('feBlend', filter, { in: 'offset0', in2: 'offset1', mode: 'screen', result: 'rg' });
    svg('feBlend', filter, { in: 'rg', in2: 'offset2', mode: 'screen' });
    function renderAt(f) {
      const p = f < peak ? 0.18 * impactAttack(f,peak,opts.riseF || 2) : pulse(f,peak,decay,0), d = amount * p;
      const values = [-d, d * 0.14, d];
      offsets.forEach((e, i) => { e.setAttribute('dx', String(values[i])); e.setAttribute('dy', String((i - 1) * d * 0.13)); });
      layer.style.filter = p > 0.00001 ? `url(#${id})` : 'none';
    }
    return finish(tl, opts, layer, renderAt);
  };

  FX.mask = function (tl, opts) {
    const start = opts.startF || 0, end = own(opts, 'endF', opts.durationF);
    const pad = own(opts, 'padding', 5), blur = Math.max(32, opts.blurPx || 40);
    const darkness = clamp(own(opts, 'darkness', 0.35), 0.25, 0.45);
    const layer = E('div', 'zr-sensitive-mask', opts.container, { position: 'absolute', left: '0', top: '0', transformOrigin: '0 0', boxSizing: 'border-box', background: `rgba(11,10,9,${darkness})`, backdropFilter: `blur(${blur}px)`, WebkitBackdropFilter: `blur(${blur}px)`, pointerEvents: 'none', zIndex: String(opts.zIndex || 15) });
    layer.setAttribute('data-layout-allow-overflow','true'); // Follows source rectangles beyond the crop.
    layer.setAttribute('data-layout-ignore','true'); // Intentional privacy occluder only; no text descendants.
    function renderAt(f) {
      const r = opts.camera ? opts.camera.screenRect(opts.srcRect || opts.rect, f) : rect(opts.rect || opts.srcRect);
      // Keep the blur radius in SOURCE pixels. A fixed screen-space blur would
      // let enlarged glyphs become readable during a camera push.
      const scale = opts.camera ? opts.camera.matrixAt(f).scale : 1;
      const screenBlur = Math.max(48, blur * scale);
      // No entrance/exit fade: sensitive pixels remain covered throughout [start,end).
      layer.style.opacity = f >= start && f < end ? '1' : '0';
      layer.style.transform = `translate(${px(r[0] - pad)},${px(r[1] - pad)})`;
      layer.style.width = px(r[2] + 2 * pad);
      layer.style.height = px(r[3] + 2 * pad);
      layer.style.backdropFilter = `blur(${screenBlur}px)`;
      layer.style.WebkitBackdropFilter = `blur(${screenBlur}px)`;
    }
    return finish(tl, opts, layer, renderAt);
  };
})(window.ZRFX);
