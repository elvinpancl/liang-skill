/* Shared v2 brand backdrop and lockup. Every state is a pure frame function.
 * Heavy beats are injected from the accents.json given to build-frames.mjs.
 * See brand-backdrop.md for opts, projection reuse and audit contracts. */
(function(FX){
  'use strict';
  const full={position:'absolute',inset:'0',width:'1920px',height:'1080px'};
  const px=n=>n.toFixed(3)+'px',mix=FX.mix,ramp=FX.ramp;
  const white='linear-gradient(180deg,#ffffff 0%,#efe6d6 100%)';
  const gold='linear-gradient(180deg,#fff8e6 0%,#ffe2a0 42%,#e9a948 78%,#c4842e 100%)';
  FX.brandTextStyle=golden=>({backgroundImage:golden?gold:white,WebkitBackgroundClip:'text',backgroundClip:'text',color:'transparent'});
  FX.brandPulseAt=function(frame,extra=[]){
    return [...(FX.brandHeavyFrames||[]),...extra].reduce((peak,at)=>{
      const age=frame-at;
      return Math.max(peak,age>=0&&age<6?Math.pow(1-age/6,2):0);
    },0);
  };
  // Geometry and depth fade default to the original terminal3d floor, shared verbatim (E3 uses these).
  // The camera-less backdrop passes BACKDROP_GRID/BACKDROP_LOOK: its default camera sees only the near
  // strip of that floor, so the grid read far weaker than E3 at 29 s. A lower floor with more far rows
  // and a gentler fade brings it to E3's brightness, from the horizon (~y 560) down.
  const BACKDROP_GRID={floorY:360,iMax:16,jMin:-24},BACKDROP_LOOK={fade:9000,power:1.6,gain:.42};
  FX.brandGrid=function(parent,geo={}){
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('width','1920');svg.setAttribute('height','1080');
    svg.setAttribute('class','zr-brand-grid');svg.setAttribute('data-layout-ignore','true');
    Object.assign(svg.style,full);parent.appendChild(svg);
    const lines=[],fy=geo.floorY??480,iMax=geo.iMax??12,jMin=geo.jMin??-10;
    function add(a,b){
      const el=document.createElementNS('http://www.w3.org/2000/svg','line');
      el.setAttribute('stroke','#e9b45a');el.setAttribute('stroke-width','1.4');svg.appendChild(el);lines.push({a,b,element:el});
    }
    for(let i=-iMax;i<=iMax;i++)for(let j=jMin;j<8;j++)add([i*280,fy,j*280],[i*280,fy,(j+1)*280]);
    for(let j=jMin;j<=8;j++)for(let i=-iMax;i<iMax;i++)add([i*280,fy,j*280],[(i+1)*280,fy,j*280]);
    function renderAt(frame,project,perspective=2200,pulse=0,look={}){
      // One 280px cell per 350 frames; periodic grid phase is deterministic.
      const advance=((frame*.8)%280+280)%280,fade=look.fade??4400,power=look.power??2,gain=look.gain??.28;
      lines.forEach(line=>{
        const a=project([line.a[0],line.a[1],line.a[2]+advance]);
        const b=project([line.b[0],line.b[1],line.b[2]+advance]);
        const visible=a.z<perspective-120&&b.z<perspective-120;
        const opacity=visible?Math.pow(FX.clamp(1.25-(perspective-(a.z+b.z)/2)/fade),power)*gain*(1+.28*pulse):0;
        for(const [key,value] of Object.entries({opacity,x1:visible?a.x:0,y1:visible?a.y:0,x2:visible?b.x:0,y2:visible?b.y:0}))line.element.setAttribute(key,String(value));
      });
    }
    return {element:svg,lines,renderAt};
  };
  FX.brandBackdrop=function(tl,opts){
    const element=FX.el('div','zr-brand-backdrop',opts.container,{...full,pointerEvents:'none',overflow:'hidden',background:'radial-gradient(ellipse 72% 64% at 50% 46%,#221c15 0%,#14100c 52%,#080706 100%)'});
    element.setAttribute('data-layout-ignore','true');
    const light=FX.el('div','zr-brand-light',element,{...full,background:'radial-gradient(ellipse 80% 75% at 50% 38%,rgba(233,180,90,.11),transparent 72%)'});
    const grid=FX.brandGrid(element,opts.manualGrid?{}:BACKDROP_GRID);
    FX.el('div','zr-brand-vignette',element,{...full,background:'radial-gradient(ellipse 80% 75% at 50% 50%,transparent 55%,rgba(0,0,0,.72) 100%)'});
    const dust=Array.from({length:28},(_,i)=>FX.el('i','zr-brand-mote',element,{position:'absolute',width:px(2+i%3),height:px(2+i%3),borderRadius:'50%',background:'#e9b45a'}));
    const frameAt=f=>f+(opts.frameOffset||0);
    function renderAt(f){
      const frame=frameAt(f),pulse=FX.brandPulseAt(frame,opts.impactFrames||[]);
      light.style.opacity=String(1+.3*pulse);
      light.style.background='radial-gradient(ellipse 80% 75% at 50% 38%,rgba(233,180,90,'+(.11+.035*pulse)+'),transparent 72%)';
      dust.forEach((d,i)=>{d.style.transform=`translate(${px((i*487.31)%1920)},${px(((i*293.17-frame*(.13+i%4*.03))%1080+1080)%1080)})`;d.style.opacity=String(.09+i%7*.023);});
      if(!opts.manualGrid)grid.renderAt(frame,p=>{
        const tilt=-3*Math.PI/180, q={x:p[0],y:p[1]*Math.cos(tilt)-p[2]*Math.sin(tilt),z:p[1]*Math.sin(tilt)+p[2]*Math.cos(tilt)};
        const scale=2200/(2200-q.z);return {x:960+q.x*scale,y:540+q.y*scale,z:q.z};
      },2200,pulse,BACKDROP_LOOK);
    }
    const proxy=FX.drive(tl,opts,renderAt);
    return {element,light,grid,dust,renderAt,frameAt,proxy};
  };
  FX.brandLockup=function(tl,opts){
    const h=opts.logoHeight||220, fs=opts.nameSize||150, gap=opts.gap||32;
    const logoW=h*FX.brand.logo.width/FX.brand.logo.height,nameW=fs*1.06*Array.from(FX.brand.name.zh).length,total=logoW+3+nameW+gap*2,top=opts.top??360;
    const element=FX.el('div','zr-brand-lockup',opts.container,{...full,fontFamily:FX.brand.fontStack,fontWeight:'800',pointerEvents:'none'});
    const ring=FX.el('div','zr-brand-ring',element,{position:'absolute',left:px((1920-total)/2+logoW/2-150),top:px(top+h/2-150),width:'300px',height:'300px',border:'3px solid '+FX.brand.colors.brand,borderRadius:'50%',boxShadow:'0 0 35px rgba('+FX.brand.rgb.brand+',.28)'});
    const row=FX.el('div','zr-brand-row',element,{position:'absolute',left:'0',top:px(top),width:'1920px',height:px(h),display:'flex',alignItems:'center',justifyContent:'center',gap:px(gap)});
    const logoBox=FX.el('div','zr-brand-logo-box',row,{position:'relative',width:px(logoW),height:px(h),borderRadius:'14px',overflow:'hidden',boxShadow:'0 0 0 1px rgba(0,0,0,.4),0 0 60px rgba('+FX.brand.rgb.brand+',.35)'});
    const logo=FX.image(FX.brand.logo.src,logoBox,{display:'block',width:'100%',height:'100%',borderRadius:'14px'});logo.alt=FX.brand.logo.alt;
    const sweep=FX.el('div','zr-brand-sweep',logoBox,{position:'absolute',left:'-140px',top:'-100px',width:'140px',height:px(h+200),background:'linear-gradient(90deg,transparent,rgba(255,217,142,.65),transparent)',transform:'skewX(-18deg)'});
    const divider=FX.el('div','zr-brand-divider',row,{width:'3px',height:px(h*.8),borderRadius:'2px',background:'rgba(246,240,230,.4)',transformOrigin:'50% 50%'});
    const crop=FX.el('div','zr-brand-name-crop',row,{width:px(nameW),height:px(fs*1.2),overflow:'hidden'});
    const name=FX.el('div','zr-brand-name',crop,{fontSize:px(fs),lineHeight:'1.2',letterSpacing:'.06em',whiteSpace:'nowrap',...FX.brandTextStyle(false)});name.textContent=FX.brand.name.zh;
    const motto=FX.el('div','zr-brand-motto',element,{position:'absolute',left:'0',top:px(opts.sloganTop??690),width:'1920px',display:'flex',justifyContent:'center',gap:'6px',fontSize:'84px',lineHeight:'1.15'});
    const chars=Array.from(opts.slogan||'').map((c,i)=>{const n=FX.el('span','zr-brand-char',motto,{display:'inline-block',...FX.brandTextStyle(i>=FX.brand.sloganSplit)});n.textContent=c;return n;});
    const start=opts.startF,land=opts.landF??start+4;
    function renderAt(f){
      const u=ramp(f,start,land,FX.ease.out),age=f-start;
      const scale=f<start? .4:f<land-1?mix(.4,1.06,ramp(f,start,land-1,FX.ease.out)):f<land?mix(1.06,1,ramp(f,land-1,land)):1;
      const breathe=opts.sloganLandF!=null&&f>=opts.sloganLandF?1+.007*Math.sin((f-opts.sloganLandF)/18):1;
      row.style.transform=`scale(${breathe})`;
      logoBox.style.opacity=f>=start?'1':'0';logoBox.style.transform=`scale(${scale})`;logoBox.style.filter=`blur(${px((1-u)*16)})`;
      logoBox.style.boxShadow=`0 0 0 1px rgba(0,0,0,.4),0 0 ${px(54+6*Math.sin(Math.max(0,f-land)/22))} rgba(${FX.brand.rgb.brand},.35)`;
      ring.style.opacity=age>=0&&age<=12?String(.32*Math.sin(Math.PI*age/12)):'0';ring.style.transform=`scale(${.4+1.4*ramp(f,start,start+12)})`;
      divider.style.transform=`scaleY(${ramp(f,opts.dividerStartF??land,opts.dividerEndF??land+8,FX.ease.out)})`;
      const reveal=ramp(f,opts.nameStartF??land+2,opts.nameEndF??land+14,FX.ease.out);name.style.transform=`translateX(${px(-(1-reveal)*nameW)})`;name.style.opacity=String(reveal);
      const sweepStart=opts.sweepStartF??land+14,sweepEnd=opts.sweepEndF??land+24;
      sweep.style.opacity=f>=sweepStart&&f<sweepEnd?'1':'0';sweep.style.transform=`translateX(${px((logoW+280)*ramp(f,sweepStart,sweepEnd))}) skewX(-18deg)`;
      chars.forEach((char,i)=>{const v=ramp(f,opts.sloganF+i*.15,opts.sloganLandF,FX.ease.out);char.style.opacity=String(v);char.style.transform=`translateY(${px((1-v)*40)}) scale(${breathe})`;});
    }
    const proxy=FX.drive(tl,opts,renderAt);
    return {element,row,logoBox,logo,divider,name,motto,characters:chars,ring,sweep,renderAt,proxy};
  };
})(window.ZRFX);
