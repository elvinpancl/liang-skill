/* filmCard. Original frame-pure media framing, 2026-10-21.
 * Media playback belongs to HyperFrames: this component never creates a video,
 * changes its source, seeks it, or rewrites its data-* timing attributes.
 * Vignette and grain use the canonical data-color-grading details contract on
 * the actual media. Persist that contract in the authored HTML before render.
 */
(function (FX) {
  'use strict';
  if (!FX) throw new Error('Load ZRFX core.js before film-card.js');

  const DETAILS = Object.freeze({vignette:.24, grain:.12, grainSize:.25, grainRoughness:.5});
  const px = value => `${Number(value.toFixed(5))}px`;
  const FULL = {position:'absolute',inset:'0',width:'1920px',height:'1080px',boxSizing:'border-box'};

  FX.filmCard = function (tl, opts) {
    if (!opts || !opts.container || !opts.element || !(opts.durationF > 0)) {
      throw new Error('filmCard: container, existing media element and positive durationF are required');
    }
    const mode = opts.mode || 'card';
    if (mode !== 'card' && mode !== 'full') throw new Error('filmCard: mode must be card or full');
    const startF = opts.startF ?? 0, endF = opts.endF ?? opts.durationF;
    const landF = opts.landF ?? Math.min(startF + 12, endF);
    const retreatF = opts.retreatF ?? null;
    const absorbStartF = opts.absorbStartF ?? null;
    const absorbEndF = opts.absorbEndF ?? endF;
    if (![startF,landF,endF,absorbEndF].every(Number.isFinite) || startF < 0 || endF <= startF || endF > opts.durationF || landF < startF || landF > endF) {
      throw new Error('filmCard: require 0 <= startF <= landF <= endF <= durationF');
    }
    if (retreatF !== null && (!Number.isFinite(retreatF) || retreatF < startF || retreatF >= endF)) {
      throw new Error('filmCard: retreatF must be inside the visible window');
    }
    if (absorbStartF !== null && (!Number.isFinite(absorbStartF) || absorbStartF < startF || absorbEndF <= absorbStartF || absorbEndF > endF)) {
      throw new Error('filmCard: require startF <= absorbStartF < absorbEndF <= endF');
    }
    const baseScale = opts.baseScale ?? 2.1;
    if (!Number.isFinite(baseScale) || baseScale <= 0 || baseScale > 2.1) throw new Error('filmCard: baseScale must be positive and at most 2.1');
    const pulseFrames = Array.from(opts.pulseFrames || []);
    if (!pulseFrames.every(Number.isFinite)) throw new Error('filmCard: pulseFrames must be finite frame numbers');
    pulseFrames.sort((a,b) => a-b);

    const element = FX.el('div','zr-film-card',opts.container,{
      ...FULL,overflow:'hidden',pointerEvents:'none',background:'#0b0a09'
    });
    element.setAttribute('data-film-card-mode',mode);
    FX.el('div','zr-film-card-light',element,{
      ...FULL,background:'radial-gradient(ellipse 65% 62% at 50% 48%,rgba(233,180,90,.12),transparent 75%)'
    });
    const width = mode === 'card' ? 405 : 1920;
    const height = mode === 'card' ? 230 : 1080;
    // All animated properties live on this non-timed wrapper. In card mode the
    // viewport is exactly 405 pixels wide: the encoded 406th black column is
    // outside its clipping edge, including while pulsing or absorbing.
    const card = FX.el('div','zr-film-card-plane',element,{
      position:'absolute',left:px((1920-width)/2),top:px((1080-height)/2),
      width:px(width),height:px(height),boxSizing:'border-box',transformOrigin:'50% 50%',
      borderRadius:mode === 'card' ? '10px' : '0',overflow:'hidden',background:'#0b0a09',
      boxShadow:mode === 'card' ? '0 24px 62px rgba(0,0,0,.62),0 0 0 1px rgba(233,180,90,.5)' : 'none'
    });
    const media = [opts.element,opts.holdElement].filter(Boolean);
    media.forEach(node => {
      // Existing canonical settings take precedence. This also makes the
      // intended finishing explicit to offline state checks; the authoring CLI
      // must persist it in static HTML for HyperFrames' media discovery.
      let grading = {};
      const existing = node.getAttribute('data-color-grading');
      if (existing) {
        try { grading = JSON.parse(existing); }
        catch (_) { throw new Error('filmCard: invalid data-color-grading JSON'); }
        if (!grading || typeof grading !== 'object' || Array.isArray(grading)) throw new Error('filmCard: data-color-grading must be an object');
      }
      node.setAttribute('data-color-grading',JSON.stringify({...grading,details:{...DETAILS,...grading.details}}));
      Object.assign(node.style,{
        position:'absolute',left:'0',top:'0',display:'block',maxWidth:'none',maxHeight:'none',
        width:mode === 'card' ? '406px' : '1920px',height:px(height),
        objectFit:mode === 'card' ? 'fill' : 'cover',objectPosition:'50% 50%'
      });
      card.appendChild(node);
    });

    function sampleAt(f) {
      const active = f >= startF && f < endF;
      const enter = FX.ramp(f,startF,landF,FX.ease.out);
      // Each specified beat has an immediate, bounded peak and a finite tail.
      let pulse = 0;
      pulseFrames.forEach(frame => {
        const age = f-frame;
        if (age >= 0 && age < 14) pulse = Math.max(pulse,Math.exp(-age/3.2)*(1-age/14));
      });
      const retreatEndF = retreatF === null ? endF : Math.min(retreatF+24,absorbStartF ?? endF);
      const retreat = retreatF === null ? 0 : FX.ramp(f,retreatF,retreatEndF,FX.ease.smooth);
      const absorb = absorbStartF === null ? 0 : FX.ramp(f,absorbStartF,absorbEndF,t=>t*t*t);
      const age = Math.max(0,f-startF);
      const restingScale = mode === 'card'
        ? Math.min(2.1,baseScale)*(.9+.1*enter)*(1-.012*pulse*(1-pulse))*(1-.18*retreat)
        : 1+.025*(1-enter)+.006*pulse+.018*(1-retreat);
      const scale = Math.min(mode === 'card' ? 2.1 : 1.1,restingScale)*(1-.98*absorb);
      const x = 0;
      const y = 0;
      const rotation = 0;
      const opacity = active ? 1-FX.clamp((absorb-.78)/.22) : 0;
      return {frame:f,mode,active,enter,pulse,retreat,absorb,scale,x,y,rotation,opacity,
        contentWidth:width,contentHeight:height,displayWidth:width*scale,displayHeight:height*scale,
        maxScale:mode === 'card' ? 2.1 : null};
    }
    function renderAt(f) {
      const state = sampleAt(f);
      element.style.opacity = state.active ? '1' : '0';
      card.style.opacity = String(state.opacity);
      card.style.transform = `translate(${px(state.x)},${px(state.y)}) rotate(${state.rotation.toFixed(5)}deg) scale(${state.scale.toFixed(7)})`;
    }
    const proxy = FX.drive(tl,opts,renderAt);
    return {element,card,sampleAt,renderAt,proxy,mode,media,gradingDetails:DETAILS};
  };
  FX.filmCard.defaultDetails = DETAILS;
})(window.ZRFX);
