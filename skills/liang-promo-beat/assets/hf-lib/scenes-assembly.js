/*
 * Adapted from video-shotcraft demos: CardFlockTumble.tsx,
 * ClonerDepthEcho.tsx and ScanlineAssembleFlyin.tsx.
 * Source commit: 43bd349a136651865ecfa6ea1cf012f6e957d304.
 * Copyright 2026 Wei Yihao. Licensed under Apache-2.0; see LICENSE-shotcraft.
 * Changed to a DOM + GSAP brand implementation: real image cards,
 * configurable frame anchors, warm-black/gold/green palette, seek-safe state.
 */
(function (FX) {
  'use strict';
  const C = {bg:FX.brand.colors.bg,gold:FX.brand.colors.gold,hi:FX.brand.colors.hi,green:FX.brand.colors.brand,ink:FX.brand.colors.ink,muted:FX.brand.colors.muted};
  const FULL = {position:'absolute',inset:'0',width:'100%',height:'100%'};
  const FONT = FX.brand.fontStack;
  const NATIVE = {clone_script:[887,655],clone_linyue:[211,314],clone_chen:[197,294],clone_wife:[197,294],clone_scene_cabin:[137,117],clone_scene_cloud:[135,117],page_script:[1904,966],page_character:[1904,966],page_storyboard:[1918,946],scan_scene_title:[670,39],scan_action:[690,80],scan_dialogue:[690,255]};
  const mix = FX.mix, clamp = FX.clamp, ramp = FX.ramp;
  const out = FX.ease.out, smooth = FX.ease.smooth;
  const inQuad = t => t * t, inCubic = t => t * t * t;
  const n = v => Number(v.toFixed(5));
  const p = v => n(v) + 'px';
  const rectStyle = r => ({position:'absolute',left:p(r[0]),top:p(r[1]),width:p(r[2]),height:p(r[3])});
  function requireOptions(opts, name) {
    if (!opts || !opts.container || !Number.isFinite(opts.durationF) || opts.durationF <= 0) {
      throw new Error(name + ': container and positive durationF are required');
    }
  }
  function stage(tl, opts, name) {
    requireOptions(opts, name);
    const root=FX.el('div','fx-'+name,opts.container,{...FULL,overflow:'hidden',background:C.bg,color:C.ink,fontFamily:FONT,boxSizing:'border-box'});
    FX.brandBackdrop(tl,{...opts,container:root});
    return FX.el('div','fx-'+name+'-content',root,{...FULL,transform:opts.contentScale?`translateY(${opts.contentY||0}px) scale(${opts.contentScale})`:'none',transformOrigin:'960px 540px'});
  }
  function label(parent, text, style) {
    const el = FX.el('div', '', parent, {fontSize:'40px',lineHeight:'1.2',fontWeight:parseFloat(style?.fontSize || '40')<=40?'600':'800',...style});
    el.textContent = text;
    return el;
  }
  function imageCard(parent, src, rect, extra, nativeSize, maxScale = 1) {
    const el = FX.el('div', 'fx-assembly-card', parent, {...rectStyle(rect),background:'#171410',border:'1px solid rgba(255,217,142,.3)',borderRadius:'14px',boxShadow:'0 24px 56px rgba(0,0,0,.48)',boxSizing:'border-box',...extra});
    const key=String(src).split('/').pop().replace(/\.[^.]*$/,'');
    const dims=nativeSize || NATIVE[key] || [rect[2],rect[3]];
    const fit=Math.min(maxScale,rect[2]/dims[0],rect[3]/dims[1]);
    const image = FX.image(src, el, {position:'absolute',left:'50%',top:'50%',transform:'translate(-50%,-50%)',width:p(dims[0]*fit),height:p(dims[1]*fit),borderRadius:'13px',objectFit:'contain'});
    return {el,image};
  }
  function intentionalDepthLayer(element) {
    // Only pure picture/decorative planes belong here. Layout ignore inherits
    // through descendants; captions and labels must remain outside this layer.
    element.setAttribute('data-layout-allow-overlap','true');
    element.setAttribute('data-layout-allow-occlusion','true');
    element.setAttribute('data-layout-ignore','true');
  }
  function svgNode(name, attrs, parent) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', name);
    Object.keys(attrs || {}).forEach(key => el.setAttribute(key, String(attrs[key])));
    if (parent) parent.appendChild(el);
    return el;
  }

  // All channels use the same continuous Catmull-Rom path. The final pose is
  // never frozen: a quadratic-in angular drift overlaps the flight's tail.
  const POSE_KEYS = ['x','y','rx','ry','rz','s'];
  function catmull(a,b,c,d,t) {
    return .5 * (2*b + (-a+c)*t + (2*a-5*b+4*c-d)*t*t + (-a+3*b-3*c+d)*t*t*t);
  }
  function splinePose(keys, u) {
    // Equal parameter intervals preserve the shared tangent at the middle key.
    const seg = u < .5 ? 0 : 1;
    const t = seg === 0 ? u * 2 : (u-.5) * 2;
    const pose = {};
    POSE_KEYS.forEach(k => {pose[k]=catmull(keys[Math.max(0,seg-1)][k],keys[seg][k],keys[seg+1][k],keys[Math.min(2,seg+2)][k],t);});
    return pose;
  }
  function mixPose(a,b,t) {
    const pose = {};
    POSE_KEYS.forEach(k => {pose[k]=mix(a[k],b[k],t);});
    return pose;
  }
  const FLOCK_POSES = [
    [{x:-8,y:-16,rx:9,ry:88,rz:12,s:1.05},{x:-135,y:-92,rx:16,ry:44,rz:-8,s:1.38},{x:-108,y:-76,rx:4,ry:13,rz:-2,s:1.62}],
    [{x:0,y:0,rx:8,ry:89,rz:12,s:1},{x:-16,y:-7,rx:13,ry:38,rz:-7,s:1.42},{x:-5,y:-2,rx:3,ry:11,rz:-2,s:1.68}],
    [{x:8,y:16,rx:7,ry:90,rz:12,s:.95},{x:112,y:78,rx:11,ry:34,rz:-6,s:1.46},{x:90,y:70,rx:2,ry:9,rz:-1,s:1.74}]
  ];
  function smokeRing(parent, cx, cy, id) {
    const svg = svgNode('svg',{viewBox:'0 0 1920 1080',width:1920,height:1080},parent);
    Object.assign(svg.style, {...FULL,overflow:'visible',mixBlendMode:'screen',pointerEvents:'none'});
    svg.setAttribute('data-layout-allow-overflow','true'); // Expanding decorative smoke.
    const defs = svgNode('defs',{},svg);
    const displacements = [];
    [11,37,73].forEach((seed,i) => {
      const filter = svgNode('filter',{id:id+'-noise-'+i,x:'-60%',y:'-60%',width:'220%',height:'220%'},defs);
      svgNode('feTurbulence',{type:'fractalNoise',baseFrequency:['0.013 0.016','0.021 0.018','0.019 0.023'][i],numOctaves:i===2?3:4,seed,result:'noise'},filter);
      displacements.push(svgNode('feDisplacementMap',{in:'SourceGraphic',in2:'noise',scale:60,xChannelSelector:'R',yChannelSelector:'G'},filter));
    });
    const gradient=svgNode('linearGradient',{id:id+'-gradient',x1:0,y1:0,x2:0,y2:1},defs);
    [[0,C.hi],[.48,C.gold],[1,'#8d6f31']].forEach(s=>svgNode('stop',{offset:s[0], 'stop-color':s[1]},gradient));
    const group=svgNode('g',{},svg), rings=[];
    // Four displaced layers describe ONE smoke volume, never concentric rings.
    const configs=[{noise:0,color:'#e9b45a',alpha:.27,width:1.9,blur:22,r:1},{noise:0,color:'url(#'+id+'-gradient)',alpha:.88,width:1,blur:9,r:1},{noise:1,color:'#fff0d0',alpha:.62,width:.42,blur:6,r:.99},{noise:2,color:'#39280d',alpha:.4,width:.4,blur:7,r:1.005}];
    configs.forEach(config=>{
      const layer=svgNode('g',{filter:'url(#'+id+'-noise-'+config.noise+')'},group);
      const ring=svgNode('circle',{cx,cy,r:46,fill:'none',stroke:config.color,opacity:config.alpha,'stroke-width':16},layer);
      ring.style.filter='blur('+config.blur+'px)';
      rings.push({ring,config});
    });
    return {svg,renderAt(t){
      const age=Math.max(0,t), grow=out(clamp(age/52));
      const radius=46+330*grow+Math.max(0,age-52)*1.6;
      const width=radius*mix(.36,.27,clamp(age/52));
      const op=t<0?0:t<4?t/4:t<30?mix(1,.94,(t-4)/26):mix(.94,.76,clamp((t-30)/30));
      group.setAttribute('opacity',String(n(op)));
      group.setAttribute('transform','rotate('+n(age*.35)+' '+cx+' '+cy+')');
      rings.forEach(({ring,config})=>{ring.setAttribute('r',String(n(radius*config.r)));ring.setAttribute('stroke-width',String(n(width*config.width)));});
      displacements.forEach((d,i)=>d.setAttribute('scale',String(n((60+grow*90)*[1,.85,1.1][i]))));
    }};
  }

  FX.cardFlockTumble = function (tl, opts) {
    const element=stage(tl,opts,'card-flock-tumble');
    const images=opts.images || [];
    if(images.length!==3) throw new Error('cardFlockTumble: images must contain exactly three sources');
    const startF=opts.flightStartF ?? 8, landF=opts.flightLandF ?? 46;
    const collapseF=opts.collapseF ?? 58, collapseDurationF=opts.collapseDurationF ?? 10;
    if(!Number.isFinite(collapseDurationF) || !(collapseDurationF>0)) throw new Error('cardFlockTumble: collapseDurationF must be positive');
    const coreF=collapseF+collapseDurationF;
    const slamF=opts.slamF ?? coreF+4, titlePeakF=opts.titlePeakF ?? null;
    const sloganF=opts.sloganF ?? (titlePeakF ?? slamF)+16, sloganLandF=opts.sloganLandF ?? null;
    if(!(startF<landF && landF<=collapseF && slamF>=coreF && slamF<opts.durationF)) throw new Error('cardFlockTumble: require flightStartF < flightLandF <= collapseF and coreF <= slamF < durationF');
    if(titlePeakF!==null && (!Number.isFinite(titlePeakF) || titlePeakF<coreF || titlePeakF>=opts.durationF)) throw new Error('cardFlockTumble: titlePeakF must be at or after coreF and before durationF');
    if(sloganLandF!==null && (!Number.isFinite(sloganLandF) || sloganLandF<=sloganF || sloganLandF>opts.durationF)) throw new Error('cardFlockTumble: sloganLandF must follow sloganF and be within durationF');
    const cx=opts.center?.[0] ?? 960, cy=opts.center?.[1] ?? 570;
    const cw=opts.cardSize?.[0] ?? 700, ch=opts.cardSize?.[1] ?? 385;
    if(opts.entryPoses!=null && (!Array.isArray(opts.entryPoses) || opts.entryPoses.length!==3 || opts.entryPoses.some(entry=>!entry || POSE_KEYS.some(key=>!Number.isFinite(entry[key]))))) {
      throw new Error('cardFlockTumble: entryPoses must contain three finite x/y/rx/ry/rz/s poses');
    }
    // Per-instance first keys only; preserve the shared staircase and collapse
    // poses and never mutate FLOCK_POSES for another composition instance.
    const flockPoses=FLOCK_POSES.map((keys,i)=>[opts.entryPoses?{...keys[0],...opts.entryPoses[i]}:keys[0],keys[1],keys[2]]);
    const id=(opts.id || opts.container.id || 'flock')+'-smoke-'+(FX._assemblyId=(FX._assemblyId || 0)+1);
    FX.el('div','',element,{...FULL,background:'radial-gradient(ellipse 48% 54% at 50% 53%, rgba(233,180,90,.22), transparent 72%)'});
    const wall=FX.el('div','',element,{...FULL});
    wall.setAttribute('data-layout-allow-overflow','true'); // Deliberately cropped decorative word wall.
    const rows=[0,1].map(i=>label(wall,FX.brand.wallText,{position:'absolute',left:'0',top:p(i?730:80),fontSize:'230px',whiteSpace:'nowrap',fontWeight:'900',color:'transparent',WebkitTextStroke:'2px rgba(233,180,90,.14)'}));
    const perspective=FX.el('div','',element,{...FULL,perspective:'1400px',perspectiveOrigin:p(cx)+' '+p(cy)});
    intentionalDepthLayer(perspective);
    const cards=images.map((src,i)=>{
      const card=imageCard(perspective,src,[cx-cw/2,cy-ch/2,cw,ch],{zIndex:String(10+i),filter:'none',transformStyle:'preserve-3d'});
      if(i<2) FX.el('div','',card.el,{...FULL,borderRadius:'14px',background:'rgba(11,10,9,'+(i===0?.2:.1)+')',pointerEvents:'none'});
      return card;
    });
    const smoke=smokeRing(element,cx,cy,id);
    const core=FX.el('div','',element,{position:'absolute',left:p(cx-420),top:p(cy-420),width:'840px',height:'840px',borderRadius:'50%',mixBlendMode:'screen',background:'radial-gradient(circle, #fff9ec 0%, rgba(255,235,188,.85) 9%, rgba(255,217,142,.45) 22%, rgba(233,180,90,.22) 44%, transparent 70%)'});
    const exposure=FX.el('div','',element,{...FULL,background:'#fff1d6',pointerEvents:'none'});
    const lockup=FX.el('div','',element,{...FULL,display:'flex',alignItems:'center',justifyContent:'center',pointerEvents:'none'});
    const brand=opts.brand ?? FX.brand.name.full;
    const canvas=document.createElement('canvas'), context=canvas.getContext('2d');
    const maxFont=opts.fontSize ?? 160, maxWidth=opts.textMaxWidth ?? 1680;
    if(context) context.font='900 '+maxFont+'px '+FONT;
    const naturalWidth=context?context.measureText(brand).width:Array.from(brand).reduce((s,c)=>s+(c.charCodeAt(0)>255?1:.65),0)*maxFont;
    const fontSize=Math.min(maxFont,maxFont*maxWidth/(1.22*(naturalWidth+Array.from(brand).length*maxFont*.06)));
    const title=label(lockup,brand,{position:'absolute',left:'0',top:p(cy-fontSize*.64),width:'1920px',textAlign:'center',fontSize:p(fontSize),fontWeight:'900',lineHeight:'1.15',whiteSpace:'nowrap',backgroundImage:'linear-gradient(180deg,#fffdf6 0%,#fff0d0 40%,#ffd98e 75%,#e9b45a 100%)',WebkitBackgroundClip:'text',backgroundClip:'text',color:'transparent',transformOrigin:'50% 50%'});
    const motto=FX.el('div','',lockup,{position:'absolute',left:'120px',top:p(cy+170),width:'1680px',display:'flex',justifyContent:'center',gap:'0',fontSize:'48px',lineHeight:'1.4',color:C.ink});
    const characters=Array.from(opts.slogan ?? FX.brand.slogan).map(c=>label(motto,c,{fontSize:'48px',display:'inline-block',whiteSpace:'pre'}));
    function driftAt(f) {
      const t=Math.max(0,Math.min(f,collapseF)-(startF+(landF-startF)*.86));
      const r=Math.pow(clamp(t/14),2);
      return {rx:t*-.1*r,ry:t*.34*r,rz:t*.05*r};
    }
    function cardPoseAt(f,i) {
      const drift=driftAt(f);
      const keys=flockPoses[i];
      let pose=splinePose(keys,out(clamp((f-startF)/(landF-startF))));
      pose={...pose,rx:pose.rx+drift.rx,ry:pose.ry+drift.ry,rz:pose.rz+drift.rz};
      if(f>=collapseF){
        const d=driftAt(collapseF), final={...keys[2],rx:keys[2].rx+d.rx,ry:keys[2].ry+d.ry,rz:keys[2].rz+d.rz};
        pose=mixPose(final,{x:[-20,0,15][i],y:[-12,0,10][i],rx:0,ry:55+i*5,rz:4,s:.08},inQuad(clamp((f-collapseF)/collapseDurationF)));
      }
      return pose;
    }
    function titleSampleAt(f) {
      if(titlePeakF===null){
        const progress=ramp(f,slamF,slamF+14,out), age=Math.max(0,f-slamF);
        return {progress,age,opacity:ramp(f,slamF,slamF+3,out),scale:mix(1.22,1,progress)+Math.max(0,age-14)*.0006,spacing:mix(.06,-.025,progress),blur:0};
      }
      // Explicit peak mode matches textSlam: anticipation is faint, while the
      // principal visibility/scale/clarity change completes on titlePeakF.
      const pre=.12*ramp(f,titlePeakF-5,titlePeakF-1,out);
      const progress=f<titlePeakF-1?pre:f<titlePeakF?mix(.12,1,inCubic(clamp(f-titlePeakF+1))):1;
      const age=Math.max(0,f-titlePeakF);
      const settle=age>0 && age<16?-.022*Math.sin(age*Math.PI/5)*Math.exp(-age/5):0;
      return {progress,age,opacity:progress,scale:1+.22*(1-progress)+settle+Math.max(0,age-14)*.0006,spacing:mix(.06,-.025,progress),blur:16*(1-progress)};
    }
    function renderAt(f) {
      const collapse=clamp((f-collapseF)/collapseDurationF), wallExit=ramp(f,collapseF,coreF+4,inCubic);
      wall.style.opacity=String(n(ramp(f,2,18,out)*(1-wallExit)));
      wall.style.transform='scale('+n(mix(1,.7,wallExit))+')';
      rows.forEach((row,i)=>row.style.transform='translateX('+p((i?1:-1)*f*2.4-(i?1000:300))+')');
      cards.forEach((card,i)=>{
        card.el.style.transform=FX.pose(cardPoseAt(f,i));
        card.el.style.opacity=String(n(1-inCubic(clamp((collapse-.6)/.4))));
        card.el.style.filter='none';
      });
      smoke.renderAt(f-coreF);
      const flash=f<coreF || f>coreF+14?0:Math.exp(-(f-coreF)/2.2);
      core.style.opacity=String(n(flash));exposure.style.opacity=String(n(.12*flash));
      const titleState=titleSampleAt(f);
      title.style.opacity=String(n(titleState.opacity));
      title.style.transform='scale('+n(titleState.scale)+')';
      title.style.letterSpacing=p(titleState.spacing*fontSize);
      const glow=.6+.4*Math.exp(-titleState.age/10);
      title.style.filter=(titlePeakF===null?'':'blur('+p(titleState.blur)+') ')+'drop-shadow(0 0 '+p(18*glow)+' rgba(255,217,142,'+n(.55*glow)+')) drop-shadow(0 0 '+p(58*glow)+' rgba(233,180,90,'+n(.4*glow)+'))';
      characters.forEach((char,i)=>{
        const stagger=sloganLandF===null?i*.7:i/Math.max(1,characters.length-1)*Math.min(2,(sloganLandF-sloganF)*.3);
        const v=ramp(f,sloganF+stagger,sloganLandF===null?sloganF+stagger+12:sloganLandF,out);
        char.style.opacity=String(n(v));char.style.transform='translateY('+p((1-v)*40)+')';
      });
    }
    const proxy=FX.drive(tl,opts,renderAt);
    let brandLockup=null;
    if(opts.brandLogo){
      title.style.display='none';motto.style.display='none';wall.style.display='none';
      smoke.svg.style.opacity='.18';exposure.style.display='none';
      brandLockup=FX.brandLockup(tl,{...opts,container:lockup,startF:coreF,landF:titlePeakF,logoHeight:220,nameSize:150,top:340,sloganTop:680,slogan:opts.slogan,sloganF,sloganLandF});
    }
    return {element,renderAt,proxy,brandLockup,cards:cards.map(c=>c.el),cardPoseAt,coreF,slamF,collapseDurationF,titlePeakF,sloganF,sloganLandF,titleSampleAt,title,motto,characters,core,exposure};
  };

  FX.clonerDepthEcho = function (tl, opts) {
    const element=stage(tl,opts,'cloner-depth-echo');
    if(!opts.img) throw new Error('clonerDepthEcho: img is required');
    const sources=(opts.clones || []).map(c=>typeof c==='string'?{img:c}:c);
    if(!sources.length) throw new Error('clonerDepthEcho: clones must contain at least one source');
    const count=sources.length, spawnF=opts.spawnF ?? 20, staggerF=opts.staggerF ?? 2.2;
    const spreadDurationF=opts.spreadDurationF ?? 20, mergeF=opts.mergeF ?? 72;
    const mergeDurationF=opts.mergeDurationF ?? 10, mergedF=mergeF+mergeDurationF;
    if(mergeF<spawnF+(count-1)*staggerF+spreadDurationF || mergedF>=opts.durationF) throw new Error('clonerDepthEcho: mergeF must follow every clone arrival; merge must finish before durationF');
    const rect=opts.cardRect ?? [90,245,960,710], gapZ=opts.gapZ ?? 100;
    const vp=opts.vanishingPoint ?? [1060,540], dx=opts.dx ?? 0, dy=opts.dy ?? 0;
    const perspectiveDepth=opts.perspective ?? 1800;
    const heroCenter=[rect[0]+rect[2]/2,rect[1]+rect[3]/2];
    const introImpactF=opts.introImpactF ?? null, introSettleF=opts.introSettleF ?? 5;
    const introGold=opts.introGold === true;
    if(introImpactF!==null && (!Number.isFinite(introImpactF) || introImpactF<0 || introImpactF>=opts.durationF || !Number.isFinite(introSettleF) || introSettleF<=0)) throw new Error('clonerDepthEcho: introImpactF must be inside the clip and introSettleF must be positive');
    FX.el('div','',element,{...FULL,background:'radial-gradient(ellipse 72% 65% at 52% 48%, rgba('+FX.brand.rgb.accent+',.12), transparent 72%)'});
    // A framing light leaves the captured UI pixels unchanged. It exists only
    // for the explicitly enabled cut-point impact; default callers are intact.
    const introHalo=introImpactF!==null && introGold?FX.el('div','',element,{...FULL,background:'radial-gradient(ellipse 680px 490px at '+p(heroCenter[0])+' '+p(heroCenter[1])+',rgba(255,240,195,.42),rgba(233,180,90,.25) 55%,transparent 85%)',pointerEvents:'none',opacity:'0'}):null;
    const dolly=FX.el('div','',element,{...FULL,transformOrigin:p(rect[0]+rect[2]/2)+' '+p(rect[1]+rect[3]/2)});
    const perspective=FX.el('div','',dolly,{...FULL,perspective:p(perspectiveDepth),perspectiveOrigin:p(vp[0])+' '+p(vp[1]),transformStyle:'preserve-3d'});
    intentionalDepthLayer(perspective);
    const cloneEls=[], cloneLabels=[], cloneRects=[], cloneLabelOffsets=[];
    for(let idx=count;idx>=1;idx--){
      const source=sources[idx-1], key=String(source.img).split('/').pop().replace(/\.[^.]*$/,'');
      const dims=source.nativeSize || NATIVE[key] || [320,480];
      const landscape=dims[0]>dims[1];
      // The two rear landscape cards use shorter x steps: perspective plus
      // the spring overshoot and dolly would otherwise push card five outside
      // the 1920px stage. The full default flight keeps a >=32px safe margin.
      const defaultX=idx<=3?1000+(idx-1)*185:1450+(idx-4)*120;
      const target=source.cardRect ?? opts.cloneRects?.[idx-1] ?? [defaultX,190+(idx-1)*40,landscape?440:400,landscape?380:600];
      cloneRects[idx-1]=target;
      cloneLabelOffsets[idx-1]=landscape?Math.max(0,idx-4)*60:0;
      const card=imageCard(perspective,source.img,target,{border:'2px solid rgba('+FX.brand.rgb.accent+',.8)',transformStyle:'preserve-3d'},dims,4);
      // These readable labels are 2D siblings, not children of the exempt 3D
      // picture group. A real label/callout collision must still be audited.
      if(source.label) cloneLabels[idx-1]=label(dolly,source.label,{position:'absolute',width:p(Array.from(source.label).length*44+8),height:'52px',fontSize:'40px',lineHeight:'1.3',color:C.ink,whiteSpace:'nowrap',zIndex:'30'});
      cloneEls[idx-1]=card.el;
    }
    const hero=imageCard(perspective,opts.img,rect,{transformStyle:'preserve-3d',border:'2px solid rgba(255,217,142,.65)'},opts.nativeSize,2);
    const rim=FX.el('div','',hero.el,{...FULL,borderRadius:'14px',boxSizing:'border-box',pointerEvents:'none'});
    const title=label(element,opts.title ?? '从剧本到角色场景',{position:'absolute',left:'110px',top:'150px',width:'900px',fontSize:'64px',lineHeight:'1.3'});
    const counter=FX.el('div','',element,{position:'absolute',left:'1110px',top:p(opts.counterY ?? (opts.counterText?900:820)),width:'720px',height:opts.counterText?'90px':'180px',transformOrigin:'0% 70%',color:C.green});
    const customCounter=opts.counterText==null?null:label(counter,String(opts.counterText),{fontSize:p(opts.counterFontSize ?? 64),lineHeight:'1.3',whiteSpace:'nowrap'});
    let previous=null,current=null;
    if(!customCounter){
      label(counter,'×',{position:'absolute',left:'0',top:'25px',fontSize:'100px',opacity:'.65'});
      previous=label(counter,'1',{position:'absolute',left:'100px',top:'0',fontSize:'160px',lineHeight:'1',fontVariantNumeric:'tabular-nums'});
      current=label(counter,'1',{position:'absolute',left:'100px',top:'0',fontSize:'160px',lineHeight:'1',fontVariantNumeric:'tabular-nums'});
      // Render only one glyph during a tick; no overlap waiver hides 2D text.
      label(element,opts.counterLabel ?? '内容资产',{position:'absolute',left:'1430px',top:'920px',fontSize:'40px',color:C.muted});
    }
    function spreadAt(f,idx) {
      if(opts.spawnPeaks){
        const peak=opts.spawnPeaks[idx-1],age=f-peak;
        if(age< -1)return .02*ramp(f,peak-5,peak-1,smooth);
        if(age<0)return mix(.02,1,age+1);
        return 1+(age<8?.025*Math.sin(age*Math.PI/4)*Math.exp(-age/3):0);
      }
      const t=clamp((f-spawnF-(idx-1)*staggerF)/spreadDurationF);
      // One bounded overshoot, matching the reference's damped spring feel.
      return t === 0 ? 0 : t === 1 ? 1 : FX.ease.overshoot(t);
    }
    function mergeAt(f){return ramp(f,mergeF,mergedF,inCubic);}
    function depthAt(f,idx){return spreadAt(f,idx)*(1-mergeAt(f));}
    function introStateAt(f){
      const age=introImpactF===null?-1:f-introImpactF;
      const active=age>=0 && age<24;
      const glow=active && introGold?Math.exp(-age/7):0;
      return {active,scale:age<0?1:mix(1.08,1,clamp(age/introSettleF)),glow,borderWidth:2+2*glow,borderOpacity:.65+.35*glow};
    }
    function renderAt(f) {
      const merge=mergeAt(f);
      const intro=introStateAt(f);
      const press=ramp(f,Math.max(0,spawnF-8),spawnF,smooth)*(1-ramp(f,spawnF,spawnF+10,out));
      const popT=clamp((f-mergedF)/16), pop=f<mergedF?0:Math.sin(popT*Math.PI)*Math.pow(1-popT,.6);
      const rimFlash=f<mergedF?0:1-clamp((f-mergedF)/14);
      const drift=14*ramp(f,spawnF+spreadDurationF,mergeF,smooth)*(1-merge);
      dolly.style.transform='scale('+n(1+.02*ramp(f,spawnF+spreadDurationF,mergeF,smooth)+.006*ramp(f,mergedF+14,opts.durationF,smooth))+')';
      cloneEls.forEach((el,i)=>{
        const idx=i+1, d=depthAt(f,idx), spread=spreadAt(f,idx);
        const born=clamp(1-(f-spawnF-i*staggerF)/8);
        const opacity=d<=.002?0:mix(1,.8,idx/count)*clamp(spread*2.5)*(1-merge*.4);
        const r=cloneRects[i], center=[r[0]+r[2]/2,r[1]+r[3]/2];
        const tx=(heroCenter[0]-center[0])*(1-d)+(dx*idx-drift*idx*.4)*d;
        const ty=(heroCenter[1]-center[1])*(1-d)+dy*idx*d;
        el.style.transform='translate3d('+p(tx)+','+p(ty)+','+p(-gapZ*idx*d)+')';
        el.style.opacity=String(n(opacity));
        el.style.boxShadow='0 0 '+p(14*born)+' rgba('+FX.brand.rgb.accent+','+n(.45*born)+')';
        const caption=cloneLabels[i];
        if(caption){
          const projection=perspectiveDepth/(perspectiveDepth+gapZ*idx*d);
          caption.style.left=p(vp[0]+(r[0]+tx-vp[0])*projection);
          caption.style.top=p(vp[1]+(r[1]+r[3]+ty-vp[1])*projection+12+cloneLabelOffsets[i]);
          // Labels appear after their spring settles and clear before recall;
          // readable 2D copy must not cross while the picture planes travel.
          const settledF=opts.spawnPeaks?opts.spawnPeaks[i]+8:spawnF+i*staggerF+spreadDurationF;
          caption.style.opacity=String(n(ramp(f,settledF,settledF+4,out)*(1-ramp(f,mergeF-6,mergeF,out))));
        }
      });
      hero.el.style.transform='scale('+n(intro.scale*(1-.04*press)*(1+.06*pop))+')';
      hero.el.style.opacity='1';
      if(introHalo)introHalo.style.opacity=String(n(intro.glow));
      if(intro.glow>0){
        hero.el.style.border=p(intro.borderWidth)+' solid rgba(255,217,142,'+n(intro.borderOpacity)+')';
        hero.el.style.boxShadow='0 24px 56px rgba(0,0,0,.48),0 0 '+p(40*intro.glow)+' rgba(255,217,142,'+n(.9*intro.glow)+'),0 0 '+p(110*intro.glow)+' rgba(233,180,90,'+n(.55*intro.glow)+')';
        rim.style.border='2px solid rgba(255,246,216,'+n(intro.glow)+')';
        rim.style.boxShadow='inset 0 0 '+p(22*intro.glow)+' rgba(255,217,142,'+n(.45*intro.glow)+')';
      }else{
        hero.el.style.border='2px solid rgba(255,217,142,.65)';
        hero.el.style.boxShadow='0 24px 56px rgba(0,0,0,.48)';
        rim.style.border='2px solid rgba('+FX.brand.rgb.accent+','+n(.25*press+.9*rimFlash)+')';
        rim.style.boxShadow='0 0 '+p(50*rimFlash)+' rgba('+FX.brand.rgb.accent+','+n(.45*rimFlash)+')';
      }
      let value=1,lastTick=-99;
      for(let idx=1;idx<=count;idx++){const tick=spawnF+(idx-1)*staggerF+2;if(f>=tick){value++;lastTick=tick;}}
      const roll=ramp(f,lastTick,lastTick+5,out), punch=f<mergedF?0:Math.sin(clamp((f-mergedF)/12)*Math.PI);
      if(previous && current){
        previous.textContent=String(value-1);current.textContent=String(value);
        previous.style.opacity=value>1 && roll<.5?'1':'0';
        current.style.opacity=value===1 || roll>=.5?'1':'0';
        previous.style.transform='translateY('+p(-roll*60)+')';current.style.transform='translateY('+p((1-roll)*60)+')';
      }
      counter.style.transform='scale('+n(1+.06*punch)+')';
      counter.style.textShadow='0 0 '+p(18+20*punch)+' rgba('+FX.brand.rgb.accent+',.25)';
      const titleIn=ramp(f,mergedF+6,mergedF+20,out);
      title.style.opacity=String(n(titleIn));title.style.transform='translateY('+p((1-titleIn)*40)+')';
    }
    const proxy=FX.drive(tl,opts,renderAt);
    return {element,renderAt,proxy,hero:hero.el,clones:cloneEls,cloneLabels,cloneRects,counter,depthAt,mergedF,introImpactF,introSettleF,introGold,introStateAt,introHalo};
  };

  FX.scanlineAssemble = function (tl, opts) {
    const element=stage(tl,opts,'scanline-assemble');
    const boardRect=opts.boardRect ?? [288,160,1344,800];
    const [ax,ay,aw,ah]=boardRect;
    const highContrast=opts.highContrast === true;
    const scanStartF=opts.scanStartF ?? 8, scanEndF=opts.scanEndF ?? 86;
    const flightF=opts.flightF ?? 14, scanY0=-20, scanY1=ah+20;
    if(!(scanStartF<scanEndF && scanEndF<opts.durationF)) throw new Error('scanlineAssemble: require scanStartF < scanEndF < durationF');
    if(!opts.blocks?.length) throw new Error('scanlineAssemble: blocks are required');
    const plan=opts.blocks.map((block,i)=>{
      const rect=block.slotRect;
      if(!rect || rect.length!==4 || rect[2]<=0 || rect[3]<=0 || !block.img) throw new Error('scanlineAssemble: each block needs img and positive slotRect');
      let from=block.from ?? 'left';
      if(typeof from==='string') from={left:[-ax-rect[0]-rect[2]-60,0],right:[1920-ax-rect[0]+60,0],top:[0,-ay-rect[1]-rect[3]-60],bottom:[0,1080-ay-rect[1]+60]}[from];
      if(!from) throw new Error('scanlineAssemble: from is left/right/top/bottom, [dx,dy], or {x,y,rotate}');
      const offset=Array.isArray(from)?from:[from.x,from.y];
      if(!offset.slice(0,2).every(Number.isFinite) || offset.length<2) throw new Error('scanlineAssemble: from must contain finite x and y offsets');
      return {...block,index:i,rect,from:offset,rotation:block.rotation ?? from.rotate ?? (offset[0]<0?-4:4),landF:block.landF ?? scanStartF+(rect[1]+rect[3]-scanY0)/(scanY1-scanY0)*(scanEndF-scanStartF)};
    });
    let previousLand=-Infinity;
    [...plan].sort((a,b)=>a.rect[1]+a.rect[3]-b.rect[1]-b.rect[3]).forEach(block=>{
      if(opts.blocks[block.index].landF==null) block.landF=Math.max(block.landF,previousLand+4);
      previousLand=block.landF;
    });
    const lastLand=Math.max(...plan.map(b=>b.landF));
    if(lastLand>scanEndF) throw new Error('scanlineAssemble: final block lands after scanEndF; widen scan window or set landF');
    const gridCSS='repeating-linear-gradient(0deg,rgba(233,180,90,.085) 0 1.5px,transparent 1.5px 120px),repeating-linear-gradient(90deg,rgba(233,180,90,.085) 0 1.5px,transparent 1.5px 120px),repeating-linear-gradient(0deg,rgba(233,180,90,.045) 0 1px,transparent 1px 24px),repeating-linear-gradient(90deg,rgba(233,180,90,.045) 0 1px,transparent 1px 24px)';
    const grid=FX.el('div','',element,{...FULL,background:gridCSS,opacity:'0'});
    const status=label(element,'装配中',{position:'absolute',left:p(ax),top:p(opts.statusY ?? ay-54),fontSize:'40px',color:C.hi});
    const stats=label(element,'',{position:'absolute',right:p(1920-ax-aw),top:p(opts.statusY ?? ay-54),fontSize:'40px',fontVariantNumeric:'tabular-nums',color:C.ink});
    const board=FX.el('div','zr-script-board',element,rectStyle(boardRect));
    const surface=FX.el('div','',board,{...FULL,borderRadius:'18px',background:highContrast?'linear-gradient(180deg,#665235,#443521)':'linear-gradient(180deg,#493d29,#30281c)',boxShadow:highContrast?'inset 0 0 0 1px rgba(255,235,192,.4),0 30px 80px rgba(0,0,0,.5),0 0 36px rgba(233,180,90,.18)':'0 30px 80px rgba(0,0,0,.5)'});
    const border=FX.el('div','',board,{...FULL,borderRadius:'18px',border:highContrast?'3px solid rgba(255,223,157,.95)':'2px solid rgba(255,217,142,.7)',boxSizing:'border-box'});
    const highlight=FX.el('div','',element,{...FULL,background:gridCSS,opacity:'0'});
    const items=plan.map(block=>{
      const [x,y,w,h]=block.rect;
      const slot=FX.el('div','',board,{...rectStyle(block.rect),border:highContrast?'2px dashed rgba(255,223,157,.8)':'1.5px dashed rgba(255,217,142,.5)',borderRadius:'10px',boxSizing:'border-box'});
      label(slot,block.label ?? ('区块 '+String(block.index+1).padStart(2,'0')),{position:'absolute',left:'14px',top:'10px',fontSize:'40px',color:highContrast?C.ink:C.muted});
      const maxScale=block.maxScale ?? opts.maxScale ?? 2.2;
      const trails=[0,1,2].map(()=>imageCard(board,block.img,block.rect,{boxShadow:'none',border:'none',opacity:'0'},block.nativeSize,maxScale).el);
      const card=imageCard(board,block.img,block.rect,{borderRadius:'10px',border:highContrast?'2px solid rgba(255,223,157,.95)':'2px solid rgba(255,217,142,.65)',background:'#171619',...(highContrast?{boxShadow:'0 0 0 1px rgba(255,223,157,.25),0 8px 20px rgba(0,0,0,.5)'}:{})},block.nativeSize,maxScale);
      card.el.setAttribute('data-layout-allow-overflow','true'); // Authored offscreen fly-in.
      trails.forEach(el=>el.setAttribute('data-layout-allow-overflow','true')); // 2D trails need no overlap/occlusion waiver.
      const svg=svgNode('svg',{width:w,height:h,viewBox:'0 0 '+w+' '+h},card.el);
      Object.assign(svg.style,{position:'absolute',inset:'0',overflow:'visible',pointerEvents:'none'});
      const corners=svgNode('path',{fill:'none',stroke:C.hi,'stroke-width':3,'stroke-linecap':'round','stroke-linejoin':'round'},svg);
      return {block,slot,card:card.el,trails,svg,corners};
    });
    const line=FX.el('div','',board,{position:'absolute',left:'-60px',top:'0',width:p(aw+120),height:'4px',background:'linear-gradient(90deg,transparent,#fff1cd 8%,#fffdf6 50%,#fff1cd 92%,transparent)',boxShadow:'0 0 12px rgba(255,217,142,.95),0 0 36px rgba(233,180,90,.6),0 0 90px rgba(233,180,90,.35)',pointerEvents:'none'});
    function poseAt(block,f) {
      const u=ramp(f,block.landF-flightF,block.landF,FX.ease.overshoot);
      return {x:mix(block.from[0],0,u),y:mix(block.from[1],0,u),rotation:mix(block.rotation,0,u)};
    }
    function renderAt(f) {
      const ly=mix(scanY0,scanY1,clamp((f-scanStartF)/(scanEndF-scanStartF)));
      const lineOn=ramp(f,scanStartF-5,scanStartF+1,out)*(1-ramp(f,scanEndF,scanEndF+10,inCubic));
      const done=ramp(f,lastLand+4,lastLand+16,out), blueprint=mix(1,.3,done);
      grid.style.opacity='0';border.style.opacity=String(n(highContrast?mix(1,.82,done):blueprint));
      const surfaceMask='linear-gradient(180deg,#000 '+p(ly-30)+',transparent '+p(ly+2)+')';
      surface.style.maskImage=surfaceMask;surface.style.webkitMaskImage=surfaceMask;
      const gridMask='linear-gradient(180deg,transparent '+p(ay+ly-180)+',#000 '+p(ay+ly)+',transparent '+p(ay+ly+2)+')';
      highlight.style.maskImage=gridMask;highlight.style.webkitMaskImage=gridMask;highlight.style.opacity='0';
      line.style.transform='translateY('+p(ly-2)+')';line.style.opacity=String(n(lineOn));
      const placed=plan.filter(block=>f>=block.landF).length;
      status.textContent=placed===plan.length?'装配完成':'装配中';status.style.color=placed===plan.length?C.green:C.gold;
      stats.textContent=String(placed).padStart(2,'0')+' / '+String(plan.length).padStart(2,'0')+'    '+(Math.max(0,Math.min(f,lastLand)-scanStartF)/(opts.fps || 30)).toFixed(1)+' s';
      items.forEach(({block,slot,card,trails,svg,corners})=>{
        const pose=poseAt(block,f), before=poseAt(block,f-.5), after=poseAt(block,f+.5);
        const opacity=ramp(f,block.landF-flightF,block.landF-flightF+4,out);
        const speed=Math.hypot(after.x-before.x,after.y-before.y);
        const blur=f>=block.landF+4?0:Math.min(18,speed*.32);
        const vx=speed>0?(after.x-before.x)/speed:0, vy=speed>0?(after.y-before.y)/speed:0;
        // Clear the readable placeholder three frames before flight begins:
        // spring overshoot can cross the target long before the landing frame.
        slot.style.opacity=String(n((1-ramp(f,block.landF-flightF-7,block.landF-flightF-3,out))*blueprint));
        card.style.transform='translate('+p(pose.x)+','+p(pose.y)+') rotate('+n(pose.rotation)+'deg)';card.style.opacity=String(n(opacity));
        trails.forEach((trail,i)=>{const length=blur*(i+1)*.8;trail.style.transform='translate('+p(pose.x-vx*length)+','+p(pose.y-vy*length)+') rotate('+n(pose.rotation)+'deg)';trail.style.opacity=String(n(opacity*clamp(blur/18)*[.14,.09,.05][i]));});
        const tick=ramp(f,block.landF+1,block.landF+4,out)*(1-ramp(f,block.landF+5,block.landF+14,out));
        const g=10+10*(1-ramp(f,block.landF+1,block.landF+7,out)), a=22, w=block.rect[2], h=block.rect[3];
        corners.setAttribute('d','M'+(-g)+' '+(-g+a)+'V'+(-g)+'H'+(-g+a)+' M'+(w+g-a)+' '+(-g)+'H'+(w+g)+'V'+(-g+a)+' M'+(w+g)+' '+(h+g-a)+'V'+(h+g)+'H'+(w+g-a)+' M'+(-g+a)+' '+(h+g)+'H'+(-g)+'V'+(h+g-a));
        svg.style.opacity=String(n(tick));
      });
    }
    const proxy=FX.drive(tl,opts,renderAt);
    return {element,renderAt,proxy,plan,lastLand,poseAt,board,boardRect,status,stats,border,surface,highContrast,blocks:items.map(item=>item.card)};
  };
})(window.ZRFX);
