// 共用：找 Playwright、Chrome、ffmpeg，读 CUES 和 DURATION，找系统字体，按卷 UUID 找外置盘。
import {existsSync,readdirSync,statSync} from 'node:fs';
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {homedir} from 'node:os';
import {spawnSync} from 'node:child_process';

// Playwright 用宿主已有的，不另装。VIDEO_NODE_MODULES 指向含 playwright 的 node_modules。
export function loadPlaywright(){
  const candidates=[process.env.VIDEO_NODE_MODULES,
    join(homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')].filter(Boolean);
  for(const dir of candidates){
    if(existsSync(join(dir,'playwright','package.json')))return createRequire(join(dir,'playwright','package.json'))('playwright');
  }
  try{return createRequire(import.meta.url)('playwright')}catch{}
  throw new Error('找不到 Playwright：设置 VIDEO_NODE_MODULES 指向含 playwright 的 node_modules（不要自行安装，先问）');
}

export function chromePath(){
  const p=process.env.VIDEO_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  if(!existsSync(p))throw new Error('找不到 Chrome：设置 VIDEO_CHROME_PATH');
  return p;
}

export const ffmpegBin=()=>process.env.FFMPEG_BIN||'ffmpeg';
export const ffmpeg=(args,opts={})=>spawnSync(ffmpegBin(),['-hide_banner',...args],{maxBuffer:1<<30,...opts});

// 源文件里的 const CUES=[...]; 和 const DURATION=...;，按字面量求值。CUES 里不能引用别的常量。
export function readTimeline(html){
  const m=html.match(/const CUES\s*=\s*(\[[\s\S]*?\]);/);
  if(!m)throw new Error('找不到 const CUES=[...];');
  const cues=Function('return '+m[1])();
  const d=html.match(/const DURATION\s*=\s*([\d.]+)/);
  if(!d)throw new Error('找不到 const DURATION=');
  return {cues,duration:Number(d[1])};
}

export function srtFromCues(cues,duration){
  const ts=x=>{const ms=Math.round(x*1000);const h=Math.floor(ms/3600000),m=Math.floor(ms/60000)%60,s=Math.floor(ms/1000)%60,r=ms%1000;
    return [h,m,s].map(v=>String(v).padStart(2,'0')).join(':')+','+String(r).padStart(3,'0')};
  // 每句从自己的开始时间显示到下一句开始前 0.05 秒，导入剪映后逐句文本朗读，配音就和画面对上
  return cues.map((c,i)=>`${i+1}\n${ts(c.t)} --> ${ts(i<cues.length-1?cues[i+1].t-0.05:duration)}\n${c.text}\n`).join('\n');
}

// macOS 可下载字体装在 AssetsV2 的哈希目录里，路径因机器而异，按文件名找最大的那份。
export function findSystemFont(name){
  const roots=['/System/Library/AssetsV2','/Library/Fonts',join(homedir(),'Library/Fonts'),'/System/Library/Fonts','/System/Library/Fonts/Supplemental'];
  const found=[];
  const walk=(dir,depth)=>{
    let entries;try{entries=readdirSync(dir,{withFileTypes:true})}catch{return}
    for(const e of entries){const p=join(dir,e.name);
      if(e.isDirectory()&&depth<6&&e.name!=='Subsets')walk(p,depth+1);
      else if(e.name===name)found.push(p)}
  };
  for(const r of roots)walk(r,0);
  return found.sort((a,b)=>statSync(b).size-statSync(a).size)[0]||null;
}

// 成品视频放外置盘时按卷 UUID 找挂载点；盘不在就停，不改存本机。
export function mediaDir(uuid,rel){
  const r=spawnSync('diskutil',['info',uuid],{encoding:'utf8'});
  const mount=r.status===0&&r.stdout.match(/^\s*Mount Point:[ \t]*(\S.*)$/m);
  if(!mount)throw new Error(`外置盘（UUID ${uuid}）未挂载，接入后再读写成品视频`);
  return join(mount[1].trim(),rel);
}

export function arg(name,fallback){
  const hit=process.argv.find(a=>a===`--${name}`||a.startsWith(`--${name}=`));
  if(!hit)return fallback;
  if(hit.includes('='))return hit.slice(hit.indexOf('=')+1);
  const next=process.argv[process.argv.indexOf(hit)+1];
  return next&&!next.startsWith('--')?next:true;
}
