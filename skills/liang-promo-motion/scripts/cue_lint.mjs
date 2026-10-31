// 检查旁白时间表的节奏：每个信息点停留 2–3 秒，最后一个动作完成后至少停 0.7 秒再转场，SRT 条数对得上。
// node cue_lint.mjs <src.html> [--min 2] [--max 3] [--tail 0.7] [--allow c10=3.6,c3=1.8] [--srt 时间轴.srt]
//
// 停留 = 下一句开始 − 本句开始（最后一句到 DURATION）。
// 某句确实需要更长（例如五步流程依次点亮），在 CUES 里给这句写 maxHold:3.6，或用 --allow 放行，并在交付说明里写原因。
// 本句写了 done（最后一个动作完成的秒数）时，检查 下一句开始 − done ≥ tail，防止「没放完就跳转」。
// 这些数来自用户反馈：「单个信息点尽量控制在 2~3 秒」「这一幕看起来没放完就跳转了」。
import {readFileSync,existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {readTimeline,arg} from './lib.mjs';

const file=resolve(process.argv[2]||'');
if(!process.argv[2]||!existsSync(file))throw new Error('用法：node cue_lint.mjs <src.html>');
const min=Number(arg('min',2)),max=Number(arg('max',3)),tail=Number(arg('tail',.7));
const allow=Object.fromEntries(String(arg('allow','')||'').split(',').filter(Boolean).map(s=>{const [k,v]=s.split('=');return [k,Number(v)]}));
const {cues,duration}=readTimeline(readFileSync(file,'utf8'));
const problems=[],rows=[];
const eps=1e-6;
cues.forEach((c,i)=>{
  const next=i<cues.length-1?cues[i+1].t:duration;
  const hold=+(next-c.t).toFixed(3);
  const limit=allow[c.id]??c.maxHold??max;
  let note='';
  if(hold<min-eps){note=`停留 ${hold} 秒，少于 ${min} 秒`;problems.push(`${c.id}「${c.text}」${note}`)}
  else if(hold>limit+eps){note=`停留 ${hold} 秒，超过 ${limit} 秒`;problems.push(`${c.id}「${c.text}」${note}`)}
  if(c.done!==undefined&&next-c.done<tail-eps){
    const msg=`动作 ${c.done} 秒完成，${(next-c.done).toFixed(2)} 秒后就切，少于 ${tail} 秒`;
    note+=(note?'；':'')+msg;problems.push(`${c.id}「${c.text}」${msg}`);
  }
  rows.push(`| ${c.id} | ${c.t} | ${hold} | ${c.text} | ${note||'通过'} |`);
});
const srt=arg('srt');
if(typeof srt==='string'){
  const n=(readFileSync(resolve(srt),'utf8').match(/-->/g)||[]).length;
  if(n!==cues.length)problems.push(`SRT 有 ${n} 条，时间表有 ${cues.length} 句`);
}
console.log(`| 句 | 开始 | 停留 | 旁白 | 结果 |\n|---|---|---|---|---|\n${rows.join('\n')}\n总长 ${duration} 秒，${cues.length} 句`);
if(problems.length){console.log('\n不通过：\n- '+problems.join('\n- '));process.exitCode=1}
else console.log('\n通过');
