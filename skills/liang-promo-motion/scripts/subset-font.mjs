// 从 ttc/ttf 里取出一个字形，只保留页面用到的字，其余字形清空。
// 字形编号和其他表保持不变，只重写 glyf 与 loca，排版、字距和原字体完全一致；7 MB 级的中文字体缩到几百 KB。
// 只支持 TrueType 轮廓（glyf）。CFF 轮廓的字体会报错。
// 来源：2026-10 片头动画，兰亭黑（Lantinghei.ttc，第 0 个中黑、第 2 个特黑）实测。

// codepoints：要保留的字符码位集合。返回 {font: Buffer, kept: 保留字形数, missing: 字体里没有的字符数}
export function subset(buf,index,codepoints){
  const base=buf.toString('ascii',0,4)==='ttcf'?buf.readUInt32BE(12+index*4):0;
  const numTables=buf.readUInt16BE(base+4);
  const tables={};
  for(let i=0;i<numTables;i++){const r=base+12+i*16;tables[buf.toString('ascii',r,r+4)]={off:buf.readUInt32BE(r+8),len:buf.readUInt32BE(r+12)}}
  if(!tables.glyf||!tables.loca)throw new Error('这个字体是 CFF 轮廓（没有 glyf 表），裁不了子集；换 glyf 字体，或不裁剪直接内嵌');
  const T=tag=>buf.subarray(tables[tag].off,tables[tag].off+tables[tag].len);
  const head=Buffer.from(T('head'));const longLoca=head.readInt16BE(50)===1;
  const numGlyphs=T('maxp').readUInt16BE(4);
  const loca=T('loca'),glyf=T('glyf');
  const gOff=i=>longLoca?loca.readUInt32BE(i*4):loca.readUInt16BE(i*2)*2;

  // 字符 → 字形编号（cmap 格式 4 / 12）
  const cmap=T('cmap');let sub=null;
  for(let i=0;i<cmap.readUInt16BE(2);i++){
    const pid=cmap.readUInt16BE(4+i*8),eid=cmap.readUInt16BE(6+i*8),off=cmap.readUInt32BE(8+i*8),fmt=cmap.readUInt16BE(off);
    if((fmt===12)&&(pid===3||pid===0))sub={off,fmt};
    else if(!sub&&fmt===4&&(pid===3||pid===0))sub={off,fmt};
  }
  if(!sub)throw new Error('找不到可用的 cmap 子表');
  const lookup=cp=>{
    const o=sub.off;
    if(sub.fmt===12){const n=cmap.readUInt32BE(o+12);for(let g=0;g<n;g++){const p=o+16+g*12;const s=cmap.readUInt32BE(p),e=cmap.readUInt32BE(p+4);if(cp>=s&&cp<=e)return cmap.readUInt32BE(p+8)+(cp-s)}return 0}
    if(cp>0xFFFF)return 0;
    const seg=cmap.readUInt16BE(o+6)/2,ends=o+14,starts=ends+seg*2+2,deltas=starts+seg*2,ros=deltas+seg*2;
    for(let s=0;s<seg;s++){
      const end=cmap.readUInt16BE(ends+s*2);if(cp>end)continue;
      const start=cmap.readUInt16BE(starts+s*2);if(cp<start)return 0;
      const delta=cmap.readInt16BE(deltas+s*2),ro=cmap.readUInt16BE(ros+s*2);
      if(ro===0)return (cp+delta)&0xFFFF;
      const gi=cmap.readUInt16BE(ros+s*2+ro+(cp-start)*2);return gi?((gi+delta)&0xFFFF):0;
    }
    return 0;
  };
  const keep=new Set([0]);let missing=0;
  for(const cp of codepoints){const g=lookup(cp);if(g)keep.add(g);else if(cp>0x2000)missing++}
  // 组合字形引用的部件也要保留
  const queue=[...keep];
  while(queue.length){const g=queue.pop();const s=gOff(g),e=gOff(g+1);if(e-s<10)continue;
    if(glyf.readInt16BE(s)>=0)continue;
    let p=s+10,more=true;
    while(more){const flags=glyf.readUInt16BE(p),gi=glyf.readUInt16BE(p+2);p+=4;
      if(!keep.has(gi)){keep.add(gi);queue.push(gi)}
      p+=(flags&1)?4:2; if(flags&8)p+=2;else if(flags&0x40)p+=4;else if(flags&0x80)p+=8;
      more=!!(flags&0x20)}}

  // 重写 glyf / loca（统一用长格式 loca）
  const parts=[];const newLoca=Buffer.alloc((numGlyphs+1)*4);let pos=0;
  for(let g=0;g<numGlyphs;g++){newLoca.writeUInt32BE(pos,g*4);
    if(keep.has(g)){const d=glyf.subarray(gOff(g),gOff(g+1));const pad=(4-d.length%4)%4;parts.push(d,Buffer.alloc(pad));pos+=d.length+pad}}
  newLoca.writeUInt32BE(pos,numGlyphs*4);
  head.writeInt16BE(1,50);head.writeUInt32BE(0,8);
  const out={...Object.fromEntries(Object.keys(tables).map(t=>[t,Buffer.from(T(t))])),head,loca:newLoca,glyf:Buffer.concat(parts)};

  // 组装字体文件
  const tags=Object.keys(out).sort();const n=tags.length;
  const sumOf=b=>{let s=0;const p=Buffer.concat([b,Buffer.alloc((4-b.length%4)%4)]);for(let i=0;i<p.length;i+=4)s=(s+p.readUInt32BE(i))>>>0;return s};
  let es=0;while((1<<(es+1))<=n)es++;
  const dirBuf=Buffer.alloc(12+n*16);dirBuf.writeUInt32BE(buf.readUInt32BE(base),0);dirBuf.writeUInt16BE(n,4);
  dirBuf.writeUInt16BE((1<<es)*16,6);dirBuf.writeUInt16BE(es,8);dirBuf.writeUInt16BE(n*16-(1<<es)*16,10);
  let off=dirBuf.length;const datas=[];
  tags.forEach((t,i)=>{const d=out[t];const r=12+i*16;dirBuf.write(t,r,'ascii');dirBuf.writeUInt32BE(sumOf(d),r+4);dirBuf.writeUInt32BE(off,r+8);dirBuf.writeUInt32BE(d.length,r+12);
    const pad=Buffer.alloc((4-d.length%4)%4);datas.push(d,pad);off+=d.length+pad.length});
  const font=Buffer.concat([dirBuf,...datas]);
  const headPos=font.indexOf(Buffer.from('head'),12);const headOff=font.readUInt32BE(headPos+8);
  font.writeUInt32BE((0xB1B0AFBA-sumOf(font))>>>0,headOff+8);
  return {font,kept:keep.size,missing};
}

// 收集一段文本里的全部字符，外加 ASCII 可见字符
export function codepointsOf(text){
  const cps=new Set();for(let c=0x20;c<0x7F;c++)cps.add(c);
  for(const ch of text){const c=ch.codePointAt(0);if(c>=0x20)cps.add(c)}
  return cps;
}
