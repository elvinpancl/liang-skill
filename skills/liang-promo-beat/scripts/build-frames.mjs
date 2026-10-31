#!/usr/bin/env node
// 把动效组件库内联进 HyperFrames 工程的每个子合成，注入品牌配置和重拍帧号。
// node build-frames.mjs --project <工程> --brand <品牌包>/brand.json --accents <accents.json> [--plate] [--lib <组件库目录>]
//                       [--brand-override '<JSON>']
//
// - 源稿：<工程>/src/*.html，<template> 里留 /* FX_JS */、/* FX_CSS */；产物：<工程>/compositions/frames/。
// - 按源稿里的 FX.<组件> 调用挑模块；间接调用时写注释 FX_USE: scenes-spatial 之类。
// - 最前面注入 window.FX_BRAND（由品牌包生成），组件的颜色、字体族、logo、名称、口号都读它。
// - 字体文件按 assets/fonts/<字体族>-<字形名>.ttf 引用（例如 LTH-Heavy.ttf），用 extract_fonts.py 从系统字体取。
//   logo 按 assets/brand/<文件名> 引用，工程里没有时从品牌包复制。
// - --plate：额外内联组件库的 jianying-plate.css 和工程的 lib/plate-extra.css（如有），给剪映切段的底片用。
// - 不联网，不往模板里留外部脚本。
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const arg=(name,fallback)=>{const i=process.argv.indexOf('--'+name);return i<0?fallback:(process.argv[i+1]&&!process.argv[i+1].startsWith('--')?process.argv[i+1]:true)};
const here=path.dirname(fileURLToPath(import.meta.url));
const project=path.resolve(arg('project')||'');
const brandFile=path.resolve(arg('brand')||'');
const accentsFile=path.resolve(arg('accents')||'');
if(!arg('project')||!fs.existsSync(path.join(project,'src')))throw new Error('需要 --project <工程>，工程里要有 src/');
if(!fs.existsSync(brandFile))throw new Error('需要 --brand <brand.json>');
if(!fs.existsSync(accentsFile))throw new Error('需要 --accents <accents.json>（analyze_frames.py 的产物）');
const lib=path.resolve(arg('lib')||path.join(here,'..','assets','hf-lib'));
const plate=!!arg('plate');
const brandDir=path.dirname(brandFile);
const brand=JSON.parse(fs.readFileSync(brandFile,'utf8'));

// 品牌配置
const c=brand.colors;
const en=brand.name.en,zh=brand.name.zh;
const logoName=path.basename(brand.logo.hires);
const [logoW,logoH]=brand.logo.hires_size;
let FX_BRAND={colors:{bg:c.bg,gold:c.gold,hi:c.gold_hi,brand:c.brand,ink:c.text,muted:c.muted,dim:c.dim,warn:c.warn},
  font:brand.fonts.family,logo:{src:'assets/brand/'+logoName,width:logoW,height:logoH,alt:en},
  name:{zh,full:`${en} ${zh}`},slogan:brand.slogan.text,sloganSplit:Array.from(brand.slogan.white).length,
  wallText:`${en.toUpperCase()} · ${zh} · ${en.toUpperCase()} · ${zh}`};
if(arg('brand-override')){const o=JSON.parse(arg('brand-override'));FX_BRAND={...FX_BRAND,...o,colors:{...FX_BRAND.colors,...(o.colors||{})}}}
const logoTarget=path.join(project,'assets','brand',logoName);
if(!fs.existsSync(logoTarget)){fs.mkdirSync(path.dirname(logoTarget),{recursive:true});fs.copyFileSync(path.join(brandDir,brand.logo.hires),logoTarget)}

// 主题样式：字体声明和舞台底色
const cap=s=>s[0].toUpperCase()+s.slice(1);
const faces=Object.entries(brand.fonts.faces).map(([key,f])=>{
  const file=f.hf_file||`${brand.fonts.family}-${cap(key)}.ttf`;
  if(!fs.existsSync(path.join(project,'assets','fonts',file)))console.warn(`提示：工程里没有 assets/fonts/${file}，先跑 extract_fonts.py`);
  return `@font-face{font-family:${brand.fonts.family};src:url('assets/fonts/${file}') format('truetype');font-weight:${f.css_weight};font-style:normal;font-display:block}`;
});
const theme=[`/* 品牌 token，由 build-frames.mjs 按品牌包生成 */`,...faces,
  `.fx-stage{position:absolute;inset:0;width:1920px;height:1080px;overflow:hidden;background:${c.bg};color:${c.text};font-family:${brand.fonts.family},sans-serif;font-weight:700}`,
  `.fx-stage *{box-sizing:border-box}`,`.fx-stage img{image-rendering:auto}`,
  `.fx-stage .fx-caption{font-size:44px;line-height:1.35;color:${c.text}}`].join('\n');
const plateCss=plate?[path.join(lib,'jianying-plate.css'),path.join(project,'lib','plate-extra.css')]
  .filter(f=>fs.existsSync(f)).map(f=>fs.readFileSync(f,'utf8')).join('\n'):'';

const libs=['core.js','common.js','brand-backdrop.js','scenes-spatial.js','scenes-assembly.js','full-scene.js','film-card.js'];
const code=Object.fromEntries(libs.map(f=>[f,fs.readFileSync(path.join(lib,f),'utf8')]));
const accents=JSON.parse(fs.readFileSync(accentsFile,'utf8'));
const heavy=accents.accents.filter(a=>a.level==='heavy').map(a=>a.frame);
const hashes={};
const outDir=path.join(project,'compositions','frames');
fs.mkdirSync(outDir,{recursive:true});
for(const name of fs.readdirSync(path.join(project,'src')).filter(f=>f.endsWith('.html'))){
  const raw=fs.readFileSync(path.join(project,'src',name),'utf8');
  const id=raw.match(/data-composition-id="([^"]+)"/)?.[1];
  const rootId=raw.match(/id="([^"]+)"\s+data-composition-id/)?.[1];
  if(!id||!rootId||!raw.includes('/* FX_JS */')||!raw.includes('/* FX_CSS */'))throw new Error(`源稿缺少 composition id 或 FX_JS/FX_CSS 标记：${name}`);
  const needed=['core.js','common.js','brand-backdrop.js'];
  if(/FX\.(basic3dScene|carousel3d|terminal3d)|FX_USE: scenes-spatial/.test(raw))needed.push('scenes-spatial.js');
  if(/FX\.(cardFlockTumble|clonerDepthEcho|scanlineAssemble)|FX_USE: scenes-assembly/.test(raw))needed.push('scenes-assembly.js');
  if(/FX\.(fullScene|filmCard)|FX_USE: full-scene/.test(raw))needed.push('full-scene.js');
  if(/FX\.filmCard|FX_USE: film-card/.test(raw))needed.push('film-card.js');
  const js='window.FX_BRAND='+JSON.stringify(FX_BRAND)+';\n'+needed.map(f=>code[f]).join('\n')+'\nwindow.ZRFX.brandHeavyFrames='+JSON.stringify(heavy)+';';
  const css=theme.replaceAll('.fx-stage',`#${rootId}`)+(plate?'\n'+plateCss.replaceAll('.fx-stage',`#${rootId}`):'');
  let out=raw.replace('/* FX_JS */',()=>js).replace('/* FX_CSS */',()=>css);
  if(plate)out=out.replace(`id="${rootId}" data-composition-id=`,`id="${rootId}" data-jy-plate="true" data-composition-id=`);
  if(/<script[^>]+src=/.test(out))throw new Error(`模板里有外部脚本：${name}`);
  fs.writeFileSync(path.join(outDir,name),out);
  hashes[name]={composition:id,libraries:needed,sha256:crypto.createHash('sha256').update(out).digest('hex')};
}
fs.mkdirSync(path.join(project,'data'),{recursive:true});
fs.writeFileSync(path.join(project,'data','build-manifest.json'),JSON.stringify({libraries:libs,mode:plate?'jianying-plate':'normal',brand:brandFile,frames:hashes},null,2)+'\n');
console.log(`已构建 ${Object.keys(hashes).length} 个子合成（${plate?'剪映底片':'正常'}模式），品牌 ${en} ${zh}，重拍 ${heavy.length} 个。`);
