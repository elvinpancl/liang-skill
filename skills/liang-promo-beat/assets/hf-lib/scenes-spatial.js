/*
 * Spatial motion recipes adapted from video-shotcraft by Wei Yihao.
 * Copyright 2026 Wei Yihao. Licensed under Apache-2.0.
 * Source commit: 43bd349a136651865ecfa6ea1cf012f6e957d304
 * Sources: demos/camera/basic-3d-scene/Basic3DScene.tsx,
 * demos/ui-entrance/carousel-3d/Carousel3D.tsx,
 * demos/camera/terminal-3d/Terminal3D.tsx.
 * Modified 2026-10-21: vanilla DOM + GSAP frame proxy,
 * configurable frame schedules, native-resolution captures, warm-black/gold.
 * No React runtime, external media, clock, or nondeterministic random values.
 */
(function (FX) {
  'use strict';
  if (!FX) throw new Error('Load ZRFX core.js before scenes-spatial.js');
  const C = { bg: FX.brand.colors.bg, gold: FX.brand.colors.gold, light: FX.brand.colors.hi, green: FX.brand.colors.brand, ink: FX.brand.colors.ink, dim: FX.brand.colors.muted };
  const rad = Math.PI / 180;
  const nativeSizes = {
    flight_story: [912, 650], page_script: [1904, 966], page_character: [1904, 966],
    page_storyboard: [1918, 946], station_05_video: [405, 230],
    terminal_step01: [395, 100], terminal_step02: [395, 100], terminal_frozen: [815, 153]
  };
  const pose = p => Object.assign({ x: 0, y: 0, z: 0, rx: 0, ry: 0, rz: 0, s: 1 }, p || {});
  const poseMix = (a, b, u) => Object.fromEntries(['x', 'y', 'z', 'rx', 'ry', 'rz', 's'].map(k => [k, FX.mix(a[k], b[k], u)]));
  const hash = n => { const v = Math.sin(n * 91.345 + 47.853) * 43758.5453; return v - Math.floor(v); };
  const px = n => `${n.toFixed(3)}px`;
  const div = (cls, parent, style) => FX.el('div', cls, parent, Object.assign({ boxSizing: 'border-box' }, style));
  const text = (value, cls, parent, style) => { const n = div(cls, parent, {fontWeight:parseFloat(style?.fontSize || '40')<=40?'600':'800',...style}); n.textContent = value; return n; };
  function stage(opts, name) {
    if (!opts.container || !(opts.durationF > 0)) throw new Error(`${name}: container and positive durationF are required`);
    const root = div(`zr-${name}`, opts.container, {
      position: 'absolute', inset: '0', width: '1920px', height: '1080px', overflow: 'hidden',
      color: C.ink, background: C.bg, fontFamily: FX.brand.fontStack
    });
    return root;
  }
  function sizeOf(item, fallback) {
    const key = String(item.img || '').split('/').pop().replace(/\.[^.]*$/, '');
    return item.nativeSize || nativeSizes[key] || (key.indexOf('style_') === 0 ? [206, 190] : fallback);
  }
  // These flags belong to moving 3D content, never to the scene root or a
  // screen-space caption. In HF 0.8.181 overlap is inherited; occlusion is not.
  function spatialLayer(element) {
    element.setAttribute('data-layout-allow-overlap', 'true');
    return element;
  }
  function spatialText(element) {
    element.setAttribute('data-layout-allow-occlusion', 'true');
    return element;
  }
  function rawImage(item, parent, maxW, maxH, maxScale = 1) {
    const sz = sizeOf(item, [maxW, maxH]);
    const scale = Math.min(maxScale, maxW / sz[0], maxH / sz[1]);
    const w = sz[0] * scale, h = sz[1] * scale;
    const image = FX.image(item.img, parent, { position: 'absolute', width: px(w), height: px(h), left: '50%', top: '50%', transform: 'translate(-50%,-50%)', objectFit: 'contain' });
    image.alt = item.label || item.title || '';
    return { image, width: w, height: h, nativeSize: sz, scale };
  }
  function flightsOf(raw, length) {
    const flights = (raw || []).map((x, i) => Array.isArray(x)
      ? { from: i, to: i + 1, startF: x[0], landF: x[1] }
      : Object.assign({ from: i, to: i + 1 }, x)).sort((a, b) => a.startF - b.startF);
    flights.forEach((x, i) => {
      if (!(x.landF > x.startF) || !Number.isInteger(x.from) || !Number.isInteger(x.to) || x.from < 0 || x.from >= length || x.to < 0 || x.to >= length) throw new Error('Invalid spatial flight');
      if (i && x.startF < flights[i - 1].landF) throw new Error('Spatial flights must not overlap');
      if (i && x.from !== flights[i - 1].to) throw new Error('Spatial flights must form a continuous station route');
    });
    return flights;
  }
  function cameraSample(f, poses, flights) {
    let current = flights.length ? flights[0].from : 0;
    let p = poses[current], index = current, moving = null, arrived = 0, next = Infinity;
    for (const fl of flights) {
      if (f < fl.startF) { next = fl.startF; break; }
      if (f < fl.landF) {
        const raw = FX.clamp((f - fl.startF) / (fl.landF - fl.startF));
        const u = FX.ease.inOut(raw);
        return { pose: poseMix(poses[fl.from], poses[fl.to], u), index: FX.mix(fl.from, fl.to, u), moving: { raw, u, flight: fl }, arrived, next: fl.landF };
      }
      current = fl.to; p = poses[current]; index = current; arrived = fl.landF;
    }
    return { pose: Object.assign({}, p), index, moving, arrived, next };
  }

  FX.basic3dScene = function (tl, opts) {
    const stations = opts.stations || [];
    if (!stations.length) throw new Error('basic3dScene requires stations');
    const root = stage(opts, 'basic3d');
    FX.brandBackdrop(tl,{...opts,container:root});
    const perspective = opts.perspective || 3000;
    const view = div('zr-basic-view', root, { position: 'absolute', inset: '0', perspective: px(perspective), perspectiveOrigin: '960px 540px' });
    const world = div('zr-basic-world', view, { position: 'absolute', left: '960px', top: '540px', width: '0', height: '0', transformStyle: 'preserve-3d' });
    world.setAttribute('data-layout-allow-overflow', 'true');
    spatialLayer(world);
    const poses = stations.map((s, i) => pose(s.pose || { x: i * 1850, y: (i % 2) * 300, z: -i * 220, ry: i % 2 ? -28 : 0 }));
    const flights = flightsOf(opts.flights, stations.length);
    const overview = opts.overview;
    const finalStation = flights.length ? flights[flights.length - 1].to : 0;
    let overPose;
    if (overview) {
      if (!(overview.landF > overview.startF)) throw new Error('overview landF must follow startF');
      if (flights.length && overview.startF < flights[flights.length - 1].landF) throw new Error('overview must follow the last flight');
      if (overview.textLandF != null && (!Number.isFinite(overview.textLandF) || overview.textLandF < 0)) throw new Error('overview textLandF must be a nonnegative frame');
      overPose = pose(Object.assign({
        x: (Math.min(...poses.map(p => p.x)) + Math.max(...poses.map(p => p.x))) / 2,
        y: (Math.min(...poses.map(p => p.y)) + Math.max(...poses.map(p => p.y))) / 2,
        z: Math.min(...poses.map(p => p.z)), s: overview.scale || 3.5
      }, overview.pose || {}));
      if (overview.scale != null) overPose.s = overview.scale;
    }
    for (let i = 0; i < (opts.dustCount == null ? 60 : opts.dustCount); i++) {
      const r = 2 + hash(i * 11.9 + 3) * 5;
      div('zr-basic-mote', world, { position: 'absolute', width: px(r * 2), height: px(r * 2), left: px(-r), top: px(-r), borderRadius: '50%', transform: `translate3d(${px(-2200 + hash(i * 3.1) * 9500)},${px(-2200 + hash(i * 5.7 + 1) * 4500)},${px(-3500 + hash(i * 7.3 + 2) * 3200)})`, background: `radial-gradient(circle,rgba(255,217,142,${.2 + hash(i + 6) * .5}),transparent 72%)` });
    }
    const cards = stations.map((s, i) => {
      const ns = sizeOf(s, [1200, 680]);
      const imageMaxScale = s.imageMaxScale ?? opts.imageMaxScale ?? 1;
      const imageScale = Math.min(imageMaxScale, (s.maxWidth || 1740) / ns[0], (s.maxHeight || 820) / ns[1]);
      const w = s.width ?? opts.cardWidth ?? Math.max(s.minWidth || 720, ns[0] * imageScale + 32);
      const h = s.height ?? opts.cardHeight ?? Math.max(s.minHeight || 420, ns[1] * imageScale + 32);
      const wrap = div('zr-basic-card', world, { position: 'absolute', width: px(w), height: px(h), left: px(-w / 2), top: px(-h / 2), transform: FX.pose(poses[i]), borderRadius: '22px', border: '1px solid rgba(233,180,90,.36)', background: '#171411', boxShadow: '0 30px 80px rgba(0,0,0,.65)', overflow: 'visible' });
      const imageHost = div('zr-basic-image', wrap, { position: 'absolute', inset: '15px', overflow: 'hidden', borderRadius: '12px' });
      const image = rawImage(s, imageHost, w - 32, h - 32, imageMaxScale);
      const caption = text(`${String(i + 1).padStart(2, '0')}  ${s.label || ''}`, 'zr-basic-label', wrap, { position: 'absolute', left: '0', bottom: '-74px', width: '100%', fontSize: `${opts.labelFontSize || 46}px`, lineHeight: '64px', color: C.ink, textAlign: 'center', whiteSpace: 'nowrap' });
      spatialText(caption); // Label attached to a 3D station, not a 2D callout.
      const progress = div('zr-basic-progress', wrap, { position: 'absolute', left: '0', bottom: '-8px', width: '100%', height: '4px', background: C.gold, transformOrigin: 'left center' });
      return { element: wrap, caption, progress, image, width: w, height: h };
    });
    const overLabel = text(overview && overview.label || '从故事到成片', 'zr-basic-overview', root, { position: 'absolute', left: '120px', top: '860px', fontSize: '68px', color: C.light, opacity: '0' });
    // Optional peak semantics keep the original gradual label entrance intact
    // for earlier scenes. With labelSlam, the station arrival is the complete,
    // clear impact frame; only a low-opacity anticipation precedes that frame.
    function labelSampleAt(f, i) {
      const arrival = i === (flights[0] ? flights[0].from : 0) ? 0 : (flights.find(x => x.to === i) || { landF: opts.durationF }).landF;
      const departure = (flights.find(x => x.from === i && x.startF >= arrival) || { startF: overview ? overview.startF : opts.durationF }).startF;
      if (!opts.labelSlam) {
        const opacity = FX.ramp(f, Math.max(0, arrival - 6), arrival + 8, FX.ease.out);
        return {arrival,departure,opacity,scale:1,blur:0,y:(1-opacity)*18,glow:0};
      }
      const pre = .12 * FX.ramp(f,arrival-5,arrival-1,FX.ease.out);
      const opacity = f < arrival-1 ? pre : f < arrival ? FX.mix(.12,1,Math.pow(FX.clamp(f-arrival+1),3)) : 1;
      const age = f-arrival;
      const settle = age > 0 && age < 16 ? -.022*Math.sin(age*Math.PI/5)*Math.exp(-age/5) : 0;
      return {arrival,departure,opacity,scale:1+.25*(1-opacity)+settle,blur:10*(1-opacity),y:0,
        glow:age < 0 ? .12*opacity : Math.exp(-age/5)};
    }
    function sampleAt(f) {
      const cam = cameraSample(f, poses, flights);
      let over = 0;
      if (overview && f >= overview.startF) {
        over = FX.ramp(f, overview.startF, overview.landF, FX.ease.inOut);
        cam.pose = poseMix(poses[finalStation], overPose, over);
        cam.index = finalStation;
        cam.moving = over < 1 ? { raw: FX.clamp((f - overview.startF) / (overview.landF - overview.startF)), u: over } : null;
      } else if (cam.moving) {
        cam.pose.s *= 1 + (opts.hop == null ? .3 : opts.hop) * Math.sin(Math.PI * cam.moving.u);
      } else {
        const holdEnd = Math.min(cam.next, overview ? overview.startF : opts.durationF);
        const hold = FX.ramp(f, cam.arrived + 4, Math.max(cam.arrived + 5, holdEnd), FX.ease.smooth);
        const restore = Number.isFinite(holdEnd) ? 1 - FX.ramp(f, Math.max(cam.arrived + 4, holdEnd - 8), holdEnd, FX.ease.smooth) : 1;
        cam.pose.s *= 1 - (opts.creep == null ? .015 : opts.creep) * hold * restore;
      }
      if (overview && f > overview.landF) cam.pose.s *= 1 - .015 * FX.ramp(f, overview.landF + 4, opts.durationF, FX.ease.smooth);
      return Object.assign(cam, { overview: over });
    }
    function renderAt(f) {
      const cam = sampleAt(f);
      world.style.transform = FX.inversePose(cam.pose);
      cards.forEach((card, i) => {
        const focus = Math.max(1 - Math.min(1, Math.abs(cam.index - i)), cam.overview);
        card.element.style.opacity = String(.22 + .78 * focus);
        card.element.style.filter = focus >= .999 ? 'none' : `blur(${px((1 - focus) * 7)})`;
        const labelState = labelSampleAt(f,i);
        const {arrival,departure} = labelState;
        card.progress.style.transform = `scaleX(${FX.ramp(f, arrival, Math.max(arrival + 1, departure), FX.ease.linear)})`;
        card.caption.style.opacity = String(labelState.opacity * (opts.hideOverviewLabels ? 1 - cam.overview : 1));
        if (opts.labelSlam) {
          card.caption.style.transform = `scale(${labelState.scale})`;
          card.caption.style.filter = `blur(${px(labelState.blur)})`;
          card.caption.style.textShadow = `0 0 ${px(24*labelState.glow)} rgba(233,180,90,${.75*labelState.glow})`;
        } else {
          card.caption.style.transform = `translateY(${px(labelState.y)})`;
        }
      });
      const textStartF = overview && overview.textLandF != null ? overview.textLandF-8 : overview ? overview.landF-8 : 0;
      const textEndF = overview && overview.textLandF != null ? overview.textLandF : overview ? overview.landF+8 : 0;
      const overviewText = overview ? FX.ramp(f,textStartF,textEndF,FX.ease.out) : 0;
      overLabel.style.opacity = String(overviewText);
      overLabel.style.transform = `translateY(${px(26*(1-overviewText))})`;
    }
    const proxy = FX.drive(tl, opts, renderAt);
    return { element: root, renderAt, sampleAt, labelSampleAt, cards, world, proxy, overLabel };
  };

  FX.carousel3d = function (tl, opts) {
    const items = (opts.cards || opts.items || []).map(x => typeof x === 'string' ? { img: x } : x);
    if (items.length < 2) throw new Error('carousel3d requires at least two cards');
    const root = stage(opts, 'carousel3d');
    FX.brandBackdrop(tl,{...opts,container:root});
    const n = items.length, radius = opts.radius || 690, w = opts.cardWidth || 340, h = opts.cardHeight || 460;
    const push = opts.push == null ? 34 : opts.push;
    const landings = opts.stepLandF || Array.from({ length: n + 1 }, (_, i) => Math.round(i * (opts.durationF - 1) / n));
    if (landings.length < 2 || landings.some((f, i) => !Number.isFinite(f) || (i && f <= landings[i - 1]))) throw new Error('stepLandF must be strictly increasing');
    const dwell = opts.dwellF == null ? 5 : opts.dwellF;
    const centerY = opts.centerY || 465;
    const view = div('zr-carousel-view', root, { position: 'absolute', inset: '0', perspective: `${opts.perspective || 2200}px`, perspectiveOrigin: `960px ${centerY}px` });
    const anchor = div('zr-carousel-anchor', view, { position: 'absolute', left: '960px', top: `${centerY}px`, width: '0', height: '0', transformStyle: 'preserve-3d', transform: `translateZ(${-radius - push}px) rotateX(${opts.tilt == null ? -9 : opts.tilt}deg)` });
    anchor.setAttribute('data-layout-allow-overflow', 'true');
    const floor = h / 2 + 18;
    div('zr-carousel-floor', anchor, { position: 'absolute', left: `${-radius * 1.35}px`, top: `${floor - radius * 1.35}px`, width: `${radius * 2.7}px`, height: `${radius * 2.7}px`, borderRadius: '50%', transform: 'rotateX(90deg)', background: 'radial-gradient(circle,rgba(233,180,90,.12),rgba(233,180,90,.035) 45%,transparent 68%)', border: '2px solid rgba(233,180,90,.1)' });
    const reflection = div('zr-carousel-reflection', anchor, { display:opts.hideReflections?'none':'block', position: 'absolute', width: '0', height: '0', transformStyle: 'preserve-3d' });
    const ring = div('zr-carousel-ring', anchor, { position: 'absolute', width: '0', height: '0', transformStyle: 'preserve-3d' });
    spatialLayer(ring);
    spatialLayer(reflection);
    function card(item, i, parent, reflected) {
      const holder = div('zr-carousel-card', parent, { position: 'absolute', left: `${-w / 2}px`, top: `${-h / 2}px`, width: `${w}px`, height: `${h}px`, transformStyle: 'preserve-3d' });
      const faces = [0, 1].map(back => {
        const face = div(`zr-carousel-face${back ? ' zr-carousel-back' : ''}`, holder, { position: 'absolute', inset: '0', borderRadius: '22px', overflow: 'hidden', backfaceVisibility: 'hidden', webkitBackfaceVisibility: 'hidden', transform: back ? 'rotateY(180deg)' : 'rotateY(0deg)', background: '#211b14', border: '2px solid rgba(233,180,90,.2)', opacity: reflected ? '.08' : '1' });
        face.style.setProperty('-webkit-backface-visibility', 'hidden');
        if (reflected) { face.style.maskImage = 'linear-gradient(180deg,transparent 35%,#000 100%)'; face.style.webkitMaskImage = face.style.maskImage; }
        spatialText(text(String(i + 1).padStart(2, '0'), 'zr-carousel-number', face, { position: 'absolute', left: '24px', top: '20px', fontSize: '40px', color: C.gold }));
        const imageHost = div('zr-carousel-image', face, { position: 'absolute', top: '78px', left: '20px', right: '20px', height: `${h - 220}px` });
        rawImage(item, imageHost, w - 40, h - 220);
        spatialText(text(item.label || '', 'zr-carousel-name', face, { position: 'absolute', left: '12px', right: '12px', bottom: '18px', minHeight: '92px', display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', fontSize: '40px', lineHeight: '46px', whiteSpace: 'normal', overflowWrap: 'anywhere' }));
        const shade = div('zr-carousel-shade', face, { position: 'absolute', inset: '0', background: C.bg, pointerEvents: 'none' });
        return { element: face, shade };
      });
      return { element: holder, faces };
    }
    const cards = items.map((x, i) => card(x, i, ring, false));
    const reflections = items.map((x, i) => card(x, i, reflection, true));
    const subtitle = div('zr-carousel-caption', root, { position: 'absolute', left: '120px', right: '120px', top: `${opts.captionY ?? 746}px`, height: '90px', overflow: 'hidden' });
    const labels = [0, 1].map(() => text('', 'zr-carousel-caption-line', subtitle, { position: 'absolute', inset: '0', textAlign: 'center', fontSize: '64px', lineHeight: '86px', color: C.ink }));
    function sampleAt(f) {
      let k = 0;
      while (k + 1 < landings.length && f >= landings[k + 1]) k++;
      let u = 0;
      if (k + 1 < landings.length) {
        const a = landings[k], b = landings[k + 1];
        const start = Math.min(b - 1, a + Math.min(dwell, (b - a) * .4));
        u = FX.ramp(f, start, b, FX.ease.smooth);
      }
      return { index: k, progress: u, spin: (k + u) * 360 / n, selected: k % n };
    }
    function renderAt(f) {
      const s = sampleAt(f);
      ring.style.transform = `rotateY(${-s.spin}deg)`;
      reflection.style.transform = `translateY(${floor * 2}px) scaleY(-1) rotateY(${-s.spin}deg)`;
      cards.forEach((c, i) => {
        const angle = ((i * 360 / n - s.spin + 540) % 360 + 360) % 360 - 180;
        const depth = (1 - Math.cos(angle * rad)) / 2;
        const hl = FX.ease.smooth(FX.clamp(1 - Math.abs(angle) / (opts.highlightAngle || 26)));
        const transform = `rotateY(${i * 360 / n}deg) translateZ(${radius + push * hl}px)`;
        c.element.style.transform = transform;
        reflections[i].element.style.transform = transform;
        c.faces.forEach(face => {
          face.shade.style.opacity = String(.7 * depth);
          face.element.style.borderColor = `rgba(233,180,90,${.18 + .72 * hl})`;
          face.element.style.boxShadow = `inset 0 1px 0 rgba(255,217,142,.16),0 0 ${20 * hl}px rgba(233,180,90,${.3 * hl})`;
        });
        reflections[i].faces.forEach(face => { face.shade.style.opacity = String(.7 * depth); });
      });
      labels.forEach((label, j) => {
        const index = (s.index + j) % n;
        label.textContent = `${String(index + 1).padStart(2, '0')} / ${String(n).padStart(2, '0')}   ${items[index].label || ''}`;
        label.style.transform = `translateY(${(j - s.progress) * 90}px)`;
        label.style.opacity = String(1 - Math.abs(j - s.progress) * .85);
      });
    }
    const proxy = FX.drive(tl, opts, renderAt);
    return { element: root, renderAt, sampleAt, cards, reflections, ring, proxy };
  };

  function rotate(q, axis, degrees) {
    const c = Math.cos(degrees * rad), s = Math.sin(degrees * rad);
    if (axis === 'x') return { x: q.x, y: q.y * c - q.z * s, z: q.y * s + q.z * c };
    if (axis === 'y') return { x: q.x * c + q.z * s, y: q.y, z: -q.x * s + q.z * c };
    return { x: q.x * c - q.y * s, y: q.x * s + q.y * c, z: q.z };
  }
  FX.terminal3d = function (tl, opts) {
    const windows = opts.windows || [];
    if (!windows.length) throw new Error('terminal3d requires windows');
    const root = stage(opts, 'terminal3d');
    const perspective = opts.perspective || 2200, tilt = opts.tilt == null ? -3 : opts.tilt;
    const poses = windows.map((w, i) => pose(w.pose || { x: (i - 1) * 1500, y: (i % 2) * 50 - 25, z: i % 2 ? 240 : -200, ry: i % 2 ? -14 : 24 }));
    const flights = flightsOf(opts.flights, windows.length);
    const views = windows.map((w, i) => w.view == null ? (opts.viewAngles || [8, -8, 9])[i % 3] : w.view);
    const peak = opts.pullPeak == null ? 1250 : opts.pullPeak;
    const backdrop=FX.brandBackdrop(tl,{...opts,container:root,manualGrid:true});
    const view = div('zr-terminal-view', root, { position: 'absolute', inset: '0', perspective: `${perspective}px`, perspectiveOrigin: '960px 540px' });
    const world = div('zr-terminal-world', view, { position: 'absolute', left: '960px', top: '540px', width: '0', height: '0', transformStyle: 'preserve-3d' });
    world.setAttribute('data-layout-allow-overflow', 'true');
    spatialLayer(world);
    const typing = windows.map((w, i) => {
      const arrival = i === (flights[0] ? flights[0].from : 0) ? 0 : (flights.find(fl => fl.to === i) || { landF: 0 }).landF;
      const range = (opts.typing || [])[i];
      const start = w.typeStartF == null ? (range ? (Array.isArray(range) ? range[0] : range.startF) : arrival + 3) : w.typeStartF;
      const end = w.typeEndF == null ? (range ? (Array.isArray(range) ? range[1] : range.endF) : start + Math.max(10, Array.from(w.typeText || '').length * 1.6)) : w.typeEndF;
      if (!(end > start) || start < arrival) throw new Error('terminal3d typing must start after arrival and have positive duration');
      const chars = Array.from(w.typeText || '');
      const weights = chars.map((c, k) => .75 + hash(i * 31 + k + 10) * .9 + (c === ' ' ? .6 : 0));
      const total = weights.reduce((a, b) => a + b, 0) || 1;
      let t = 0;
      const at = weights.map(v => { t += v; return start + t / total * (end - start); });
      return { start, end, chars, at };
    });
    const cards = windows.map((w, i) => {
      const ns = sizeOf(w, [395, 100]);
      const cardScale = w.cardScale == null ? (opts.cardScale == null ? 2.1 : opts.cardScale) : w.cardScale;
      if (!(cardScale > 0) || !Number.isFinite(cardScale)) throw new Error('terminal3d cardScale must be positive');
      // Size the window around the enlarged capture, not around an empty stage.
      // Explicit dimensions remain supported and constrain the image to contain.
      const inset = 30, bodyTop = 184, border = 4;
      const width = w.width == null ? Math.max(680, ns[0] * cardScale + inset * 2 + border) : w.width;
      const height = w.height == null ? ns[1] * cardScale + bodyTop + inset + border : w.height;
      if (!Number.isFinite(width) || !Number.isFinite(height) || !(width > inset * 2 + border) || !(height > bodyTop + inset + border)) throw new Error('terminal3d window must fit its content area');
      const wrap = div('zr-terminal-window', world, { position: 'absolute', left: `${-width / 2}px`, top: `${-height / 2}px`, width: `${width}px`, height: `${height}px`, transform: FX.pose(poses[i]), background: 'linear-gradient(135deg,rgba(105,86,57,.9),rgba(49,42,32,.96) 58%,rgba(66,54,36,.92))', border: '2px solid rgba(255,210,125,.86)', borderRadius: '22px', boxShadow: 'inset 0 1px 0 rgba(255,245,215,.4),inset 0 0 50px rgba(255,217,142,.06),0 30px 90px rgba(0,0,0,.65),0 0 28px rgba(233,180,90,.14)', overflow: 'hidden' });
      const titlebar = div('zr-terminal-titlebar', wrap, { position: 'absolute', left: '0', right: '0', top: '0', height: '164px', padding: '18px 30px', borderBottom: '1px solid rgba(255,217,142,.48)', background: 'linear-gradient(180deg,rgba(255,235,190,.17),rgba(233,180,90,.04))' });
      spatialText(text(`${String(i + 1).padStart(2, '0')}  ${w.title || ''}`, 'zr-terminal-title', titlebar, { fontSize: '48px', lineHeight: '58px', color: C.ink, whiteSpace: 'nowrap' }));
      const line = div('zr-terminal-type-line', titlebar, { display: 'flex', alignItems: 'center', height: '66px', gap: '10px', fontSize: '52px', lineHeight: '62px', color: C.light, whiteSpace: 'pre' });
      spatialText(text('>', 'zr-terminal-prompt', line, { display: 'inline-block', fontSize: '52px', color: C.green }));
      const typed = spatialText(text('', 'zr-terminal-typed', line, { display: 'inline-block', fontSize: '52px' }));
      const caret = div('zr-terminal-caret', line, { width: '22px', height: '50px', flexShrink: '0', background: C.green });
      const body = div('zr-terminal-image', wrap, { position: 'absolute', left: `${inset}px`, right: `${inset}px`, top: `${bodyTop}px`, bottom: `${inset}px`, borderRadius: '10px', overflow: 'hidden' });
      const image = rawImage(w, body, width - inset * 2 - border, height - bodyTop - inset - border, cardScale);
      return { element: wrap, typed, caret, image, body, width, height, cardScale };
    });
    // Overview titles live in screen space so pulling back never shrinks their
    // readable type. Their positions follow the same deterministic projection.
    const overviewLabels = opts.overviewLabelFontSize ? windows.map((w, i) => text(
      `${String(i + 1).padStart(2, '0')} ${w.title || ''}`, 'zr-terminal-overview-label', root,
      { position: 'absolute', left: '0', top: '0', width: '520px', height: '62px',
        fontSize: `${opts.overviewLabelFontSize}px`, lineHeight: '62px', textAlign: 'center',
        whiteSpace: 'nowrap', color: C.light, opacity: '0' }
    )) : [];
    function sampleAt(f) {
      const cam = cameraSample(f, poses, flights);
      let side = views[Math.round(cam.index)] || 0;
      let pull = 180 * (1 - FX.ramp(f, 0, opts.entryLandF ?? Math.min(18, opts.durationF / 6), FX.ease.out));
      if (cam.moving) {
        side = FX.mix(views[cam.moving.flight.from], views[cam.moving.flight.to], cam.moving.u);
        pull += Math.sin(Math.PI * Math.pow(cam.moving.raw, .85)) * peak;
      }
      const lastLand = flights.length ? flights[flights.length - 1].landF : 0;
      if(!opts.overview) pull -= 24 * FX.ramp(f, Math.max(lastLand + 16, opts.durationF - 24), opts.durationF, FX.ease.smooth);
      let overview=0,dive=0;
      if(opts.overview && f>=opts.overview.startF){
        const o=opts.overview,last=flights.length?flights[flights.length-1].to:0;
        overview=FX.ramp(f,o.startF,o.landF,FX.ease.inOut);
        const wide=pose(o.pose||{x:0,y:0,z:0,s:3.5});
        cam.pose=poseMix(poses[last],wide,overview);
        side=FX.mix(views[last]||0,0,overview);pull=0;
        if(opts.dive && f>=opts.dive.startF){
          const d=opts.dive;dive=FX.ramp(f,d.startF,d.landF,FX.ease.inOut);
          cam.pose=poseMix(wide,pose({...poses[d.station??last],s:d.scale??.6}),dive);
          side=FX.mix(0,views[d.station??last]||0,dive);
        }
      }
      return Object.assign(cam, { side, pull, overview, dive });
    }
    function projectAt(p, cam) {
      let q = { x: p[0] - cam.pose.x, y: p[1] - cam.pose.y, z: p[2] - cam.pose.z };
      q = rotate(q, 'x', -cam.pose.rx); q = rotate(q, 'y', -cam.pose.ry); q = rotate(q, 'z', -cam.pose.rz);
      q = { x: q.x / cam.pose.s, y: q.y / cam.pose.s, z: q.z / cam.pose.s };
      q = rotate(q, 'y', cam.side); q = rotate(q, 'x', tilt); q.z -= cam.pull;
      const scale = perspective / (perspective - q.z);
      return { x: 960 + q.x * scale, y: 540 + q.y * scale, z: q.z, scale };
    }
    function renderAt(f) {
      const cam = sampleAt(f);
      world.style.transform = `translateZ(${-cam.pull}px) rotateX(${tilt}deg) rotateY(${cam.side}deg) ${FX.inversePose(cam.pose)}`;
      cards.forEach((card, i) => {
        const wide = FX.clamp(cam.pull / Math.max(1, peak));
        const focus = FX.clamp(Math.max(0, 1 - Math.abs(cam.index - i) * 1.25) + wide * .45 + cam.overview*(1-cam.dive));
        card.element.style.filter = focus >= .999 ? 'none' : `blur(${(1 - focus) * 3}px)`;
        card.element.style.opacity = String(.64 + .36 * focus);
        const ty = typing[i];
        const count = ty.at.filter(at => f >= at).length;
        card.typed.textContent = ty.chars.slice(0, count).join('');
        card.caret.style.opacity = f >= ty.start && f < ty.end ? '1' : (Math.floor(Math.max(0, f - ty.end) / 8) % 2 ? '0' : '.8');
        if (overviewLabels[i]) {
          const anchor = projectAt([poses[i].x, poses[i].y - card.height / 2, poses[i].z], cam);
          overviewLabels[i].style.transform = `translate(${anchor.x - 260}px,${anchor.y - 76}px)`;
          overviewLabels[i].style.opacity = String(FX.ease.smooth(cam.overview) * (1 - cam.dive));
        }
      });
      const globalFrame=f+(opts.frameOffset||0);
      backdrop.grid.renderAt(globalFrame,p=>projectAt(p,cam),perspective,FX.brandPulseAt(globalFrame));
    }
    const proxy = FX.drive(tl, opts, renderAt);
    return { element: root, renderAt, sampleAt, projectAt, cards, world, typing, overviewLabels, backdrop, proxy };
  };
})(window.ZRFX);
