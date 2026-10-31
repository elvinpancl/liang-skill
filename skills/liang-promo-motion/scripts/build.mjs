// 把源 HTML 打包成离线单文件：注入品牌样式和品牌文字，按文案裁字体子集并内嵌，内嵌全部图片，按 CUES 出旁白时间轴 SRT。
// 用法：node build.mjs <src.html> --brand <brand.json> --out <成品.html> [--srt <时间轴.srt>] [--sfx <音效卡点.md>]
//        [--expect-cues N] [--fonts-dir <目录>] [--no-subset]
//
// 源文件里认这几个标记（模板 assets/template.src.html 都有）：
//   /*BRAND_CSS*/                      换成品牌包 brand.css 的内容
//   const BRAND=/*BRAND*/{...}/*BRAND_END*/;   换成品牌包里的名称、口号、字体族
//   const ASSET_SRC=/*ASSETS*/{键:'相对路径'}/*ASSETS_END*/;   图片表；'brand:logo' 指品牌包的 2x logo，'brand:logo_original' 指原图
//   url("fonts/xxx")                   字体，相对源文件目录；文件名等于品牌包某个字形的 subset_file 时，按当前文案重新裁子集
//   const SFX=[{t,what}]               可选，生成音效卡点表
// 相对路径都相对源文件所在目录。
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {dirname,join,extname,resolve} from 'node:path';
import {subset,codepointsOf} from './subset-font.mjs';
import {readTimeline,srtFromCues,findSystemFont,arg} from './lib.mjs';

const srcFile=resolve(process.argv[2]||'');
if(!process.argv[2]||!existsSync(srcFile))throw new Error('用法：node build.mjs <src.html> --brand <brand.json> --out <成品.html>');
const srcDir=dirname(srcFile);
const brandFile=resolve(arg('brand')||'');
const outFile=resolve(arg('out')||'');
if(!existsSync(brandFile)||!arg('out'))throw new Error('需要 --brand <brand.json> 和 --out <成品.html>');
const brandDir=dirname(brandFile);
const brand=JSON.parse(await readFile(brandFile,'utf8'));
const fontsDir=resolve(arg('fonts-dir')||join(srcDir,'fonts'));
const mime={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp','.svg':'image/svg+xml',
  '.otf':'font/otf','.ttf':'font/ttf','.woff2':'font/woff2','.mp4':'video/mp4'};
const dataURI=async file=>{const type=mime[extname(file).toLowerCase()];if(!type)throw new Error('不认识的文件类型：'+file);
  return `data:${type};base64,`+(await readFile(file)).toString('base64')};

let html=await readFile(srcFile,'utf8');

// 1. 品牌样式与品牌文字
if(html.includes('/*BRAND_CSS*/')){
  const css=join(brandDir,'brand.css');
  if(!existsSync(css))throw new Error('品牌包里没有 brand.css：'+css);
  html=html.replace('/*BRAND_CSS*/',await readFile(css,'utf8'));
}
const brandText={en:brand.name.en,zh:brand.name.zh,full:brand.name.full,slogan:brand.slogan,font:brand.fonts.family};
html=html.replace(/\/\*BRAND\*\/[\s\S]*?\/\*BRAND_END\*\//,JSON.stringify(brandText));

// 2. 字体：品牌包里登记过的子集按当前文案重裁；系统里找不到字体时沿用已有文件
const faces=Object.values(brand.fonts.faces||{}).filter(f=>f.subset_file);
const fontRefs=[...new Set([...html.matchAll(/url\("(fonts\/[^"]+)"\)/g)].map(m=>m[1]))];
const ttcPath=process.env.BRAND_FONT_PATH||findSystemFont(brand.fonts.system_ttc);
if(!arg('no-subset')&&faces.some(f=>fontRefs.includes('fonts/'+f.subset_file))){
  if(ttcPath){
    const ttc=await readFile(ttcPath);
    const cps=codepointsOf(html);
    await mkdir(fontsDir,{recursive:true});
    for(const f of faces){
      if(!fontRefs.includes('fonts/'+f.subset_file))continue;
      const {font,kept,missing}=subset(ttc,f.ttc_index,cps);
      await writeFile(join(fontsDir,f.subset_file),font);
      console.log(`字体子集 ${f.subset_file}：保留 ${kept} 个字形，${(font.length/1024).toFixed(0)} KB；字体里没有的字符 ${missing} 个（由系统字体补齐）`);
    }
  }else console.log(`本机找不到 ${brand.fonts.system_ttc}，沿用 ${fontsDir} 里已有的子集`);
}
for(const rel of fontRefs){
  const name=rel.slice('fonts/'.length);
  const file=[join(fontsDir,name),join(srcDir,rel)].find(existsSync);
  if(!file)throw new Error('字体文件不存在：'+rel+'（先在有该字体的机器上构建一次，或去掉 --no-subset）');
  html=html.split(`url("${rel}")`).join(`url("${await dataURI(file)}")`);
}

// 3. 图片表
const m=html.match(/const ASSET_SRC=\/\*ASSETS\*\/(\{[\s\S]*?\})\/\*ASSETS_END\*\//);
if(m){
  const table=Function('return '+m[1])();
  const brandAssets={'brand:logo':brand.logo.hires,'brand:logo_original':brand.logo.original};
  const inlined={};
  for(const [k,rel] of Object.entries(table)){
    const file=brandAssets[rel]?join(brandDir,brandAssets[rel]):join(srcDir,rel);
    if(!existsSync(file))throw new Error(`素材不存在：${k} → ${file}`);
    inlined[k]=await dataURI(file);
  }
  html=html.replace(m[0],'const ASSET_SRC='+JSON.stringify(inlined)+';');
}
const leftover=[...html.matchAll(/(?:src|href)="(?!data:|#|https?:)([^"]+\.(?:png|jpe?g|webp|svg|mp4|css|js))"/g)].map(x=>x[1]);
if(leftover.length)throw new Error('还有没内嵌的外部文件：'+leftover.join(', '));
await mkdir(dirname(outFile),{recursive:true});
await writeFile(outFile,html);
console.log(`已生成：${outFile}（${(Buffer.byteLength(html)/1048576).toFixed(2)} MB）`);

// 4. 旁白时间轴与音效卡点
const {cues,duration}=readTimeline(html);
const expect=arg('expect-cues');
if(expect&&cues.length!==Number(expect))throw new Error(`时间表应有 ${expect} 句，实际 ${cues.length}`);
if(arg('srt')){await writeFile(resolve(arg('srt')),srtFromCues(cues,duration));console.log('已生成：'+resolve(arg('srt')))}
const sfx=html.match(/const SFX\s*=\s*(\[[\s\S]*?\]);/);
if(arg('sfx')&&sfx){
  const rows=Function('return '+sfx[1])();
  await writeFile(resolve(arg('sfx')),'| 秒 | 音效 |\n|---|---|\n'+rows.map(r=>`| ${r.t} | ${r.what} |`).join('\n')+'\n');
  console.log('已生成：'+resolve(arg('sfx')));
}
