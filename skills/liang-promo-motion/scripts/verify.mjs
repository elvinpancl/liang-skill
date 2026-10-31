// 成片验收：完整解码、规格、帧数、音轨，以及和网页样帧逐帧比色差。
// node verify.mjs <成片> --duration <秒> [--fps 30] [--samples 样帧目录] [--alpha] [--out 验收.json]
// 样帧是同一个 HTML 截的 JPEG，文件名 t<秒>.jpg；按帧序号取帧比对，不按时间定位，避免落到相邻帧。
// 平均绝对误差 < 4（0–255）算通过，误差来自 JPEG 压缩和 4:2:0 色度抽样。
import {writeFile,readdir} from 'node:fs/promises';
import {existsSync,openSync,readSync,fstatSync,closeSync} from 'node:fs';
import {join,resolve,dirname,basename} from 'node:path';
import {ffmpeg,arg} from './lib.mjs';

const video=resolve(process.argv[2]||'');
if(!process.argv[2]||!existsSync(video))throw new Error('用法：node verify.mjs <成片> --duration <秒>');
const fps=Number(arg('fps',30));
const duration=Number(arg('duration'));
if(!duration)throw new Error('需要 --duration');
const alpha=!!arg('alpha');
const expectedFrames=Math.round(duration*fps);

const probe=ffmpeg(['-i',video]).stderr.toString();
const stream=(probe.match(/Stream #0:0.*Video:.*/)||[''])[0];
// 完整解码一遍，同时用 -progress 计帧：新版 ffmpeg 在 -c copy 时不再输出 frame=，不能靠它数
const decode=ffmpeg(['-v','error','-nostats','-progress','pipe:1','-i',video,'-map','0:v','-f','null','-']);
const frames=Number((decode.stdout.toString().match(/^frame=(\d+)/gm)||['frame=0']).pop().replace(/\D/g,''));
const decodeErrors=decode.stderr.toString().trim();

const rgb=(file,frame)=>{const vf=(frame===undefined?'':`select=eq(n\\,${frame}),`)+'scale=480:270:flags=area';
  return ffmpeg(['-i',file,'-vf',vf,'-vsync','0','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-']).stdout};
const samples=[];
const sampleDir=arg('samples');
if(typeof sampleDir==='string'){
  // 透明成片和样帧背景不同，只比不透明部分没有意义，透明模式跳过色差比对
  if(!alpha){
    const files=(await readdir(resolve(sampleDir))).filter(f=>/^t[\d.]+\.jpg$/.test(f)).sort();
    for(const f of files){
      const frame=Math.min(frames-1,Math.round(parseFloat(f.slice(1))*fps));
      const a=rgb(join(resolve(sampleDir),f)),b=rgb(video,frame);
      let sum=0;for(let i=0;i<a.length;i++)sum+=Math.abs(a[i]-b[i]);
      samples.push({sample:f,frame,meanAbsError:+(sum/a.length).toFixed(2)});
    }
  }
}
// 老版 ffmpeg 读 ProRes 不显示色彩标记，直接在文件头尾找 mov 的 colr/nclc 原子：primaries、transfer、matrix 都是 1 即 bt709
function movTaggedBt709(file){
  const fd=openSync(file,'r');const size=fstatSync(fd).size;const chunk=Math.min(size,8<<20);
  const parts=[[0,chunk],[Math.max(0,size-chunk),chunk]].map(([pos,len])=>{const b=Buffer.alloc(len);readSync(fd,b,0,len,pos);return b});
  closeSync(fd);
  const want=Buffer.from([0x63,0x6f,0x6c,0x72,0x6e,0x63,0x6c,0x63,0,1,0,1,0,1]);
  return parts.some(b=>b.includes(want));
}
const checks=alpha
  ?{prores4444:/prores.*4444|ap4h/i.test(stream),alpha:/yuva/.test(stream)}
  :{h264:/h264/.test(stream),yuv420p:/yuv420p/.test(stream)};
Object.assign(checks,{size1080p:/1920x1080/.test(stream),fps:new RegExp(`\\b${fps} fps`).test(stream),bt709:/bt709/.test(stream)||(alpha&&movTaggedBt709(video)),
  frameCount:frames===expectedFrames,fullDecodeClean:decode.status===0&&!decodeErrors,noAudio:!/Audio:/.test(probe)});
if(samples.length)checks.samplesMatch=samples.every(s=>s.meanAbsError<4);
const worst=samples.reduce((m,s)=>!m||s.meanAbsError>m.meanAbsError?s:m,null);
const result={file:basename(video),stream,frames,expectedFrames,checks,passed:Object.values(checks).every(Boolean),
  decodeErrors:decodeErrors||null,worstSample:worst,samples};
const out=resolve(arg('out')||join(dirname(video),basename(video).replace(/\.[^.]+$/,'')+'_验收.json'));
await writeFile(out,JSON.stringify(result,null,2));
console.log(JSON.stringify({passed:result.passed,checks,frames,worstSample:worst},null,1));
console.log('验收记录：'+out);
if(!result.passed)process.exitCode=1;
