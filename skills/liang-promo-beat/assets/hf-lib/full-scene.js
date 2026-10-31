/* Task 06 scene assembly helpers. Pure frame state, no media playback control. */
(function(FX){
  'use strict';
  FX.fullScene=function(tl,root,offset,durationF){
    const opts={container:root,durationF,fps:30,frameOffset:offset}, L=f=>f-offset;
    const audit={frameOffset:offset,durationF,gates:[],callouts:[],masks:[],cameras:{},events:[]};
    const gate=(element,start,end)=>{
      const startF=L(start),endF=L(end);
      FX.drive(tl,opts,f=>{element.style.opacity=f>=startF&&f<endF?'1':'0';});
      audit.gates.push({element,startF,endF});return element;
    };
    const cue=({container=root,camera,srcRect,sourceRectAt,rect,text,start,end,cut=end,labelPos=[80,930],readEnd=end-6})=>{
      const handle=FX.callout(tl,{...opts,container,scope:root,camera,srcRect,rect,text,
        target:sourceRectAt?f=>camera.screenRect(sourceRectAt(f),f):undefined,
        startF:L(start),endF:L(end),cutF:L(cut),fontSize:46,labelPos,revealF:0,enterF:0,exitF:6});
      audit.callouts.push({handle,text,anchor:start,end,readStart:start,readEnd,cut,camera,srcRect,sourceRectAt,parent:container});
      return handle;
    };
    const camera=(name,element,container,keys)=>{
      const c=FX.camera(tl,{...opts,container,element,keyframes:keys.map(k=>({...k,f:L(k.f)}))});
      audit.cameras[name]=c;return c;
    };
    const mask=(camera,container,srcRect,start,end)=>{
      const startF=L(start)-.001,endF=L(end)+.001,padding=8;
      const handle=FX.mask(tl,{...opts,container,camera,srcRect,startF,endF,padding,blurPx:40,darkness:.35});
      audit.masks.push({handle,camera,srcRect,startF,endF,padding});return handle;
    };
    const chapter=(number,title,start,end,previousNumber=Number(number)-1)=>{
      const mount=FX.el('div','zr-chapter-window',root,{position:'absolute',inset:'0',zIndex:'60',pointerEvents:'none'});
      const handle=FX.chapterTag(tl,{...opts,container:mount,number,previousNumber,title,position:[68,48],startF:L(start),endF:L(end)+6,zIndex:60});
      gate(mount,start,end);
      audit.chapters=audit.chapters||[];audit.chapters.push({handle,number,previousNumber,title,start,end});return handle;
    };
    const caption=({container=root,text,start,end,cut=end,y=930,fontSize=48,riseF=0})=>{
      const element=FX.el('div','zr-full-caption',container,{position:'absolute',inset:'0',zIndex:'45',pointerEvents:'none'});
      const label=FX.el('div','',element,{position:'absolute',left:'100px',top:y+'px',width:'1720px',height:'90px',fontSize:fontSize+'px',lineHeight:'80px',textAlign:'center',color:'#f6f0e6',whiteSpace:'nowrap'});
      label.textContent=text;
      FX.drive(tl,opts,f=>{element.style.opacity=f>=L(start)&&f<L(cut)?'1':'0';const leave=FX.ramp(f,L(end)-6,L(end));label.style.opacity=String(1-leave);label.style.transform=`translateY(${(riseF?30*(1-FX.ramp(f,L(start),L(start)+riseF)):0)-14*leave}px)`;});
      const handle={element,label};audit.callouts.push({handle,text,anchor:start,end,cut,readStart:start,readEnd:Math.min(end-6,cut-1),parent:container});return handle;
    };
    return {opts,L,audit,gate,cue,camera,mask,chapter,caption};
  };
})(window.ZRFX);
