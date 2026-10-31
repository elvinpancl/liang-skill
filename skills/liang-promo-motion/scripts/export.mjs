// 用无头 Chrome 逐帧截图，导出成片或样帧。
// node export.mjs <成品.html> --samples [--times=0,1.5,3] [--out-dir 样帧目录]
//     截样帧并拼总览。默认时刻：每句旁白开始后 0.3 秒、中点、下一句前 0.1 秒，以及片尾前 0.05 秒。
//     流程节点、界面切换这类动作，用 --times 把每个节点亮起后的时刻也加进来。
// node export.mjs <成品.html> --render --out <成片.mp4|.mov> [--alpha] [--fps 30] [--verify-samples 样帧目录]
//     导出 1920×1080 H.264（bt709）；--alpha 导出带透明通道的 ProRes 4444 .mov，页面背景透明。
//     给了 --verify-samples 就在导出后自动验收。
// --volume-uuid <UUID> --media-rel <盘内相对目录> 时，--out 只写文件名，成片写到外置盘；盘不在就停。
//
// 页面约定（模板都有）：window.ready、window.renderFrame(t)、window.SHORT_INFO={duration,cues,fontFamily}，
// ?export=1 隐藏控件，?alpha=1 透明背景。
import {writeFile,mkdir,readdir} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {pathToFileURL,fileURLToPath} from 'node:url';
import {dirname,join,resolve,basename} from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {loadPlaywright,chromePath,ffmpegBin,ffmpeg,mediaDir,arg} from './lib.mjs';

const htmlFile=resolve(process.argv[2]||'');
if(!process.argv[2]||!existsSync(htmlFile))throw new Error('用法：node export.mjs <成品.html> --samples | --render --out <文件>');
const fps=Number(arg('fps',30)),width=1920,height=1080;
const alpha=!!arg('alpha');
const {chromium}=loadPlaywright();
const browser=await chromium.launch({executablePath:chromePath(),headless:true,
  args:['--force-color-profile=srgb','--disable-background-timer-throttling','--disable-renderer-backgrounding','--allow-file-access-from-files']});
const errors=[],external=[];
let info;
try{
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  await page.route(/^https?:\/\//,route=>{external.push(route.request().url());route.abort()});
  await page.goto(pathToFileURL(htmlFile).href+'?export=1'+(alpha?'&alpha=1':''),{waitUntil:'load'});
  await page.evaluate(()=>window.ready);
  info=await page.evaluate(()=>{const f=window.SHORT_INFO.fontFamily;
    return {duration:window.SHORT_INFO.duration,cues:window.SHORT_INFO.cues,fontFamily:f,
      font:!f||(document.fonts.check(`800 100px "${f}"`)&&document.fonts.check(`600 100px "${f}"`)),
      broken:[...document.images].filter(i=>!i.complete||!i.naturalWidth).map(i=>i.dataset.asset||i.src.slice(0,40))}});
  console.log(`页面已加载：${info.duration} 秒，${info.cues.length} 句旁白，字体 ${info.fontFamily}`);
  if(info.broken.length)throw new Error('有图片没加载：'+info.broken.join(','));
  if(!info.font)throw new Error('品牌字体没加载：'+info.fontFamily);
  const shot=()=>page.screenshot({type:'png',omitBackground:alpha});

  if(arg('samples')){
    const custom=arg('times');
    const times=typeof custom==='string'?custom.split(',').map(Number):info.cues.flatMap((c,i)=>{
      const end=i<info.cues.length-1?info.cues[i+1].t:info.duration;
      return [c.t+.3,(c.t+end)/2,end-.1]}).concat(info.duration-.05);
    const outDir=resolve(arg('out-dir')||join(dirname(htmlFile),'样帧'));
    await mkdir(outDir,{recursive:true});
    const files=[];
    for(const t of [...new Set(times.map(x=>+Math.min(info.duration,Math.max(0,x)).toFixed(2)))].sort((a,b)=>a-b)){
      await page.evaluate(t=>window.renderFrame(t),t);
      const f=join(outDir,'t'+t.toFixed(2).padStart(5,'0')+'.jpg');
      await page.screenshot({path:f,type:'jpeg',quality:82});
      files.push(f);
    }
    // 总览：每行 4 张
    const list=join(outDir,'总览清单.txt');
    await writeFile(list,files.map(f=>`file '${f.replace(/'/g,"'\\''")}'`).join('\n')+'\n');
    const r=ffmpeg(['-loglevel','error','-y','-f','concat','-safe','0','-i',list,'-vf',`scale=480:270,tile=4x${Math.ceil(files.length/4)}`,
      '-frames:v','1',join(outDir,'总览.jpg')]);
    console.log(`样帧 ${files.length} 张：${outDir}`+(r.status===0?'，总览.jpg 已生成':'，总览没拼成（不影响样帧）'));
  }

  if(arg('render')){
    let out=arg('out');
    if(typeof out!=='string')throw new Error('--render 需要 --out <文件>');
    if(arg('volume-uuid'))out=join(mediaDir(arg('volume-uuid'),arg('media-rel')||''),basename(out));
    out=resolve(out);
    await mkdir(dirname(out),{recursive:true});
    // 网页像素是 sRGB，按 Rec.709 矩阵转 YUV 并写色彩标记，和录屏原片一致
    const codec=alpha
      ?['-vf','scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuva444p10le','-c:v','prores_ks','-profile:v','4444',
        '-pix_fmt','yuva444p10le','-alpha_bits','16','-movflags','+write_colr']
      :['-vf','scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p','-c:v','libx264','-preset','slow','-crf','14',
        '-profile:v','high','-tune','animation','-movflags','+faststart'];
    const pending=out.replace(/(\.[^.]+)$/,'.partial$1');
    const ff=spawn(ffmpegBin(),['-hide_banner','-loglevel','warning','-y','-f','image2pipe','-framerate',String(fps),'-vcodec','png',
      '-i','pipe:0','-an',...codec,'-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',pending],{stdio:['pipe','ignore','pipe']});
    let log='';ff.stderr.on('data',d=>log+=d.toString());
    const done=new Promise((ok,fail)=>{ff.on('error',fail);ff.on('close',c=>c===0?ok():fail(new Error('ffmpeg 编码失败：'+log)))});
    done.catch(()=>{});ff.stdin.on('error',()=>{});
    const total=Math.round(info.duration*fps);
    const started=Date.now();
    for(let i=0;i<total;i++){
      await page.evaluate(t=>window.renderFrame(t),i/fps);
      const img=await shot();
      if(ff.exitCode!==null)throw new Error('编码器提前退出：'+log);
      if(!ff.stdin.write(img))await once(ff.stdin,'drain');
      if(i%150===0||i===total-1)console.log(`已渲染 ${i+1} / ${total} 帧（${((Date.now()-started)/1000).toFixed(0)} 秒）`);
    }
    ff.stdin.end();await done;
    // 写完再改名：外置盘中途断开时不会留下一个看起来完整的残缺文件
    const {renameSync}=await import('node:fs');renameSync(pending,out);
    console.log('导出完成：'+out+(log?'\nffmpeg 提示：'+log.trim():''));
    info.output=out;
  }
}finally{await browser.close()}
if(errors.length){console.log('页面错误：\n'+errors.join('\n'));process.exitCode=1}
if(external.length){console.log('外部请求（已拦截）：'+external.join(', '));process.exitCode=1}

if(info.output&&arg('verify-samples')){
  const verify=join(dirname(fileURLToPath(import.meta.url)),'verify.mjs');
  const args=[verify,info.output,'--duration',String(info.duration),'--fps',String(fps),'--samples',resolve(arg('verify-samples'))];
  if(alpha)args.push('--alpha');
  // 验收记录是过程文件，默认写进成品 HTML 旁边的 制作过程/，不写到外置盘的成片旁边
  const processDir=join(dirname(htmlFile),'制作过程');
  const report=arg('verify-out')||(existsSync(processDir)?join(processDir,basename(info.output).replace(/\.[^.]+$/,'')+'_验收.json'):null);
  if(report)args.push('--out',resolve(report));
  const v=spawn(process.execPath,args,{stdio:'inherit'});
  const [code]=await once(v,'close');
  if(code)process.exitCode=code;
}
