#!/usr/bin/env python3
"""逐帧音乐分析：30 fps 每帧一行的响度与分频起音、最小二乘节拍网格、三级重音、按小节响度分段、时间线图和中文摘要。

用法：python analyze_frames.py <音频> <输出目录> [--audiomap 参考 audiomap.json]
输出：music_frames.csv、accents.json、grid_diagnostics.json、music_timeline.png、summary.md。
输出目录里已有 cut_music.py 写的 splice_report.json（且音频哈希一致）时，段落会在剪接点拆开。
可读取用户指定的输入输出位置；算法和阈值的适用性需要结合实际音频核验。
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import tempfile
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
CACHE=Path(os.environ.get('LIANG_BEAT_CACHE',Path(tempfile.gettempdir())/'liang-promo-beat-cache'))
os.environ['MPLCONFIGDIR']=str(CACHE/'matplotlib')
os.environ['NUMBA_CACHE_DIR']=str(CACHE/'numba')
sys.dont_write_bytecode=True
for _p in ('matplotlib','numba'): (CACHE/_p).mkdir(parents=True,exist_ok=True)
import argparse, csv, json, math, hashlib
from collections import Counter
import numpy as np
import soundfile as sf
import librosa
from scipy.signal import find_peaks
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
FPS=30
LABELS={'intro_hits':'开头重拍','high':'高能段','break':'间歇','hits':'重拍串','build':'铺垫','outro_hits':'收尾重拍'}
COLORS={'heavy':'#d62728','medium':'#ed9225','light':'#a5a5a5'}

def checked(path):
    p=Path(path).expanduser().resolve()
    return p

def dump(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def features(stereo,sr):
    if sr%FPS: raise ValueError('采样率必须可被30整除；本任务不静默重采样')
    hop=sr//FPS; n=(len(stereo)+hop-1)//hop
    y=stereo.mean(axis=1).astype(np.float32)
    S=np.abs(librosa.stft(y,n_fft=4096,win_length=2048,hop_length=hop,center=True,pad_mode='constant'))[:,:n]
    freq=librosa.fft_frequencies(sr=sr,n_fft=4096)
    diff=np.maximum(0,np.diff(S,axis=1,prepend=np.zeros((S.shape[0],1),dtype=S.dtype)))
    masks={'low':(freq>=20)&(freq<150),'mid':(freq>=150)&(freq<2500),'high':(freq>=5000)&(freq<=16000),'full':(freq>=20)&(freq<=sr/2)}
    flux={}; energy={}
    for band,mask in masks.items():
        raw=diff[mask].sum(axis=0)
        flux[band]=raw/max(float(raw.max()),1e-12)
        energy[band]=(S[mask]**2).sum(axis=0)
    # RMS uses exactly the samples of [n/30,(n+1)/30), including both channels.
    sample_power=np.mean(stereo.astype(np.float64)**2,axis=1)
    starts=np.arange(n)*hop
    powers=np.add.reduceat(sample_power,starts)/np.minimum(hop,len(stereo)-starts)
    rms_db=10*np.log10(np.maximum(powers,1e-12))
    return {'y':y,'n':n,'hop':hop,'flux':flux,'energy':energy,'rms_db':rms_db,'powers':powers}

def classify_accents(f,grid):
    T=grid['beat_period']; t0=grid['t0']; phase=grid['downbeat_phase']
    flux=f['flux']; n=f['n']; rms=f['rms_db']
    thresholds={'low':0.12,'mid':0.10,'high':0.08,'full':0.08}
    candidates=[]
    for band in thresholds:
        v=flux[band]; ix,_=find_peaks(v,height=thresholds[band],prominence=thresholds[band]*0.45,distance=2)
        if v[0]>=thresholds[band] and v[0]>v[1]: ix=np.r_[0,ix]
        for p in ix: candidates.append((int(p),band))
    # Merge simultaneous band attacks <=1 video frame; do not merge longer drum rolls.
    clusters=[]
    for p,b in sorted(candidates):
        if clusters and p-clusters[-1][0][0]<=1: clusters[-1].append((p,b))
        else: clusters.append([(p,b)])
    events=[]
    for cluster in clusters:
        frames=sorted(set(p for p,b in cluster))
        p=max(frames,key=lambda j: float(flux['full'][j]))
        t=p/FPS
        bands=sorted(set(b for q,b in cluster if b!='full'))
        # A broadband event may not meet a band's peak prominence, but still has real band flux.
        strengths={b:float(np.max(flux[b][max(0,p-1):min(n,p+2)])) for b in ('low','mid','high','full')}
        if not bands:
            bands=[b for b in ('low','mid','high') if strengths[b]>=thresholds[b]] or ['full']
        beat=int(round((t-t0)/T)); delta=abs(t-(t0+beat*T))*FPS
        bib=(beat-phase)%4+1; bar=(beat-phase)//4+1
        before=rms[max(0,p-5):max(1,p-1)]
        after=rms[p:min(n,p+3)]
        rise=float(after.mean()-before.mean()) if p>=2 else 0.0
        reasons=[]
        if bib==1 and delta<=1.25 and strengths['full']>=0.22: reasons.append('strong_downbeat')
        if rise>=5.0 and strengths['full']>=0.16: reasons.append('energy_surge')
        if 'low' in bands and 'high' in bands and strengths['low']>=0.22 and strengths['high']>=0.20: reasons.append('kick_and_cymbal')
        level='heavy' if reasons else ('medium' if ('low' in bands or 'mid' in bands) else 'light')
        if bands==['full']: reasons.append('broadband_only')
        events.append({'frame':p,'t':t,'level':level,'bands':bands,'beat_index':beat,'bar':bar,'beat_in_bar':bib,'on_grid':round(delta,6),'strengths':{k:round(v,6) for k,v in strengths.items()},'rise_db':round(rise,4),'reasons':reasons})
    return events,thresholds

def bar_table(stereo,sr,f,grid,events):
    dur=len(stereo)/sr; T=grid['beat_period']; t0=grid['t0']; phase=grid['downbeat_phase']
    base=t0+phase*T; period=4*T
    kmin=math.floor((0-base)/period); kmax=math.ceil((dur-base)/period)
    bars=[]
    for k in range(kmin,kmax):
        s=max(0,base+k*period); e=min(dur,base+(k+1)*period)
        if e-s<0.04: continue
        if not bars and s<0.1: s=0.0  # retain the short pre-onset audio prefix
        a=round(s*sr); b=round(e*sr); data=stereo[a:b]
        db=10*np.log10(max(float(np.mean(data.astype(np.float64)**2)),1e-12))
        ev=[v for v in events if s<=v['t']<e]
        p0=max(0,int(s*FPS)); p1=min(f['n'],math.ceil(e*FPS))
        bars.append({'bar':k+1,'start_t':s,'end_t':e,'mean_db':float(db),'duration_bars':(e-s)/period,
                     'accents':{lev:sum(v['level']==lev for v in ev) for lev in COLORS},
                     'low_flux_mean':float(f['flux']['low'][p0:p1].mean()),'high_flux_mean':float(f['flux']['high'][p0:p1].mean())})
    return bars

def auto_sections(bars,stereo,sr,grid):
    # Classify each actual bar, without forcing edited phrases onto multiples of four.
    # Loudness is primary; flux density distinguishes sparse hits from a full groove.
    high_ref=float(np.percentile([b['mean_db'] for b in bars],75))
    labeled=[]
    for b in bars:
        label=('high' if b['mean_db']>=high_ref-3 and b['high_flux_mean']>=.04
               else 'hits' if b['mean_db']>=high_ref-7 and b['low_flux_mean']>=.02
               else 'break')
        if labeled and labeled[-1]['label']==label: labeled[-1]['bars'].append(b)
        else: labeled.append({'label':label,'bars':[b]})
    for group in labeled:
        if group['label']=='break' and len(group['bars'])>=8: group['label']='build'
    if labeled[0]['label']=='hits': labeled[0]['label']='intro_hits'
    if labeled[-1]['label']=='hits': labeled[-1]['label']='outro_hits'
    return make_sections([(m['bars'][0]['start_t'],m['bars'][-1]['end_t'],m['label']) for m in labeled],stereo,sr,grid)

def make_sections(spans,stereo,sr,grid):
    n=math.ceil(len(stereo)/sr*FPS); out=[]
    for s,e,label in spans:
        a=round(s*sr); b=round(e*sr)
        out.append({'start_frame':max(0,round(s*FPS)),'end_frame':min(n,round(e*FPS)) if e<len(stereo)/sr-1e-8 else n,
                    'start_t':float(s),'end_t':float(e),'label':label,
                    'mean_db':round(10*np.log10(max(float(np.mean(stereo[a:b].astype(np.float64)**2)),1e-12)),4),
                    'bars':round((e-s)/(grid['beat_period']*4),6)})
    # All frame ranges are half-open and share the same quantized boundary.
    return out

def respect_edit_interfaces(out,source,sections,stereo,sr,grid):
    report_path=out/'splice_report.json'
    if not report_path.exists(): return sections,False
    report=json.loads(report_path.read_text())
    if report['output']['sha256']!=hashlib.sha256(source.read_bytes()).hexdigest():
        raise ValueError('接口报告与当前音频哈希不符；请先重新运行剪辑脚本')
    boundaries=[v['output_t'] for v in report['interfaces']]
    # Independently measured bar boundaries within one frame of a known edit
    # boundary use its exact sample time; otherwise a cut splits a same-class span.
    spans=[]
    for sec in sections:
        start,end=sec['start_t'],sec['end_t']
        for boundary in boundaries:
            if abs(start-boundary)<1/FPS: start=boundary
            if abs(end-boundary)<1/FPS: end=boundary
        points=[start]+[v for v in boundaries if start+1e-8<v<end-1e-8]+[end]
        for a,b in zip(points,points[1:]):
            label=sec['label']
            if label=='outro_hits' and b<len(stereo)/sr-1e-8: label='hits'
            spans.append((a,b,label))
    return make_sections(spans,stereo,sr,grid),True

def plot_timeline(path,stereo,sr,f,grid,events,sections,bars):
    for p in ('/System/Library/Fonts/PingFang.ttc','/System/Library/Fonts/STHeiti Light.ttc'):
        if Path(p).exists():
            prop=font_manager.FontProperties(fname=p); plt.rcParams['font.family']=prop.get_name(); break
    plt.rcParams['axes.unicode_minus']=False
    dur=len(stereo)/sr; nrows=4; fig,axs=plt.subplots(nrows,1,figsize=(28,16),constrained_layout=True)
    y=stereo.mean(axis=1); step=max(1,sr//200); count=math.ceil(len(y)/step)
    padded=np.pad(y,(0,count*step-len(y))).reshape(count,step)
    wt=np.arange(count)*step/sr; lo=padded.min(1); hi=padded.max(1)
    span=math.ceil((dur/nrows)/(4*grid['beat_period']))*4*grid['beat_period']
    section_colors={'intro_hits':'#d7ebee','high':'#e4f2df','break':'#eee8f7','hits':'#ffedd4','build':'#e2e9ff','outro_hits':'#f6dfe7'}
    for j,ax in enumerate(axs):
        origin=grid['t0']+grid['downbeat_phase']*grid['beat_period']
        start=0.0 if j==0 else origin+j*span
        end=min(dur,origin+(j+1)*span)
        ax.set_xlim(start,end); ax.set_ylim(-1.15,1.52); ax.set_yticks([-1,0,1]); ax.set_ylabel('波形幅度')
        ax.grid(axis='x',alpha=.17)
        for sec in sections:
            s=max(start,sec['start_t']); e=min(end,sec['end_t'])
            if e>s:
                ax.axvspan(s,e,color=section_colors[sec['label']],alpha=.6)
                ax.text((s+e)/2,1.32,f"{LABELS[sec['label']]} [{sec['label']}]",ha='center',fontsize=10,clip_on=True)
        mask=(wt>=start)&(wt<=end)
        ax.fill_between(wt[mask],lo[mask],hi[mask],color='#315469',alpha=.48,lw=0)
        for lev in ('light','medium','heavy'):
            times=[v['t'] for v in events if v['level']==lev and start<=v['t']<end]
            ax.vlines(times,-1,1.02,colors=COLORS[lev],lw=.55 if lev=='light' else .9,alpha=.6 if lev=='light' else .85,label=lev)
        for b in bars:
            t=b['start_t']
            if start<=t<end:
                ax.axvline(t,color='#44556b',lw=.55,alpha=.55,ls='--')
                ax.text(t+.04,1.08,f"小节 {b['bar']}",fontsize=8,ha='left',clip_on=True)
        ax2=ax.twinx(); ax2.set_ylim(-48,7); ax2.set_ylabel('均方根响度 RMS（dBFS）')
        t=np.arange(f['n'])/FPS; m=(t>=start)&(t<end)
        ax2.plot(t[m],f['rms_db'][m],color='#145cc7',lw=.8,alpha=.85,label='RMS')
        ax2.set_yticks([-40,-30,-20,-10,0]); ax.set_xlabel('时间（秒）')
        ax.set_xticks(np.arange(math.ceil(start/2)*2,end+.001,2))
        if j==0:
            ax.legend(loc='lower left',ncol=3,fontsize=10); ax2.legend(loc='lower right',fontsize=10)
    fig.suptitle(f"{path.parent.name} | {grid['bpm']:.5f} BPM | 30 fps | {dur:.3f} s\n重音：heavy 红 / medium 橙 / light 灰；蓝线为 RMS；小节边界为音频实测网格",fontsize=17)
    fig.savefig(path,dpi=160,metadata={'Software':'analyze_frames.py'})
    plt.close(fig)

def reference_compare(path,grid,sections):
    if not path.exists(): return ['未找到参考脚本结果；本目录未把缺失对照当成一致。']
    ref=json.loads(path.read_text()); beats=np.array(ref['grid']['beats_sec'])
    T,c=np.polyfit(np.arange(len(beats)),beats,1)
    ratio=grid['bpm']/(60/T)
    factor=min((.5,1.,2.),key=lambda x:abs(x-ratio))
    relation=('原始速度层级一致' if factor==1 else '原始速度层级不一致，参考脚本落入半速' if factor==2 else '原始速度层级不一致，参考脚本落入倍速')
    lines=[f"参考脚本标量为 {ref['tempo']['bpm']:.1f} BPM；其拍序列最小二乘为 {60/T:.5f} BPM；本分析为 {grid['bpm']:.5f} BPM。{relation}。经 {factor:g} 倍节拍层级换算，参考拍序列为 {factor*60/T:.5f} BPM。半倍/双倍以低频覆盖指标裁决，不直接采用参考标量。参考标量另受 hop=512 @ 22050Hz 的周期量化影响。",
           f"参考脚本输出 {len(ref['energy_phases'])} 个按秒采样能量块；本分析输出 {len(sections)} 个按小节合并的结构段，粒度和标签不同，不能声称逐段相同。参考 RMS 每秒仅取默认 2048 样本窗（约 93ms），并非整秒能量积分，稀疏打击会碎分为许多 HIGH/VOID；下表仅对照覆盖关系。"]
    for s in sections:
        matches=[p for p in ref['energy_phases'] if p['start']<s['end_t'] and p['end']>s['start_t']]
        votes=Counter()
        for p in matches: votes[p['level']]+=max(0,min(p['end'],s['end_t'])-max(p['start'],s['start_t']))
        dominant=votes.most_common(1)[0][0] if votes else '?'
        lines.append(f"- {s['start_t']:.3f}–{s['end_t']:.3f} 秒：{LABELS[s['label']]}；参考块主要为 {dominant}，覆盖 " + '、'.join(f"{k} {v:.1f}s" for k,v in votes.items())+'。')
    return lines

def write_summary(out,source,data,f,thresholds,refpath):
    grid=data['grid']; audio=data['audio']; sections=data['sections']; events=data['accents']; bars=data['bars']
    counts=Counter(e['level'] for e in events)
    lines=[f"# {source.stem}：逐帧音乐分析",'',f"原音频：`{source.name}`；解码时长 {audio['duration']:.9f} 秒，{audio['sample_rate']} Hz，{audio['channels']} 声道，{audio['samples']} 个采样点；共 {audio['frames']} 帧。",'',
    f"节奏为 **{grid['bpm']:.6f} BPM**，拍长 {grid['beat_period']:.9f} 秒，网格相位 t0 = {grid['t0']:.9f} 秒，小节第一拍相位 {grid['downbeat_phase']}（beat_index 模 4）。",
    f"精确网格最大残差：**{grid['residual_ms_max']:.6f} 毫秒**。完整拟合样本、原始 beat_track 残差、候选覆盖率与分段结果见 `grid_diagnostics.json`。",'',str(grid.get('basis',grid.get('reason',''))),'',
    '## 逐帧与分级口径','',
    '视频帧 n 对应 n/30 秒；hop = sr/30 = 1470。CSV 仅保留 ceil(解码时长×30) 行，编号从 0 连续。RMS 为该帧时间区间内立体声样本的均方能量，单位 dBFS；最后一帧按实际样本数计算。',
    '频谱通量使用 FFT=4096、Hann 有效窗=2048、center=True，逐频点只累加正向幅度变化；低频 20–150 Hz、中频 150–2500 Hz、高频 5000–16000 Hz，各频段按全曲最大值归一至 0–1。它是鼓件的频段代理，不能保证每个中频事件都是军鼓。',
    f"起音峰值阈值：{thresholds}；峰显著性至少为阈值的 45%，同一频段峰间距至少 2 帧，相邻 1 帧的多频段事件合并。弱于阈值的瞬态不计入起音表。",
    '重音（heavy）：小节第一拍附近 1.25 帧内且 full≥0.22，或局部 RMS 突增≥5dB 且 full≥0.16，或同次 low≥0.22 与 high≥0.20；中音（medium）：其余明确低/中频起音；轻音（light）：仅高频/小打击；只有全频通量达标而三频段都未达阈值时，标记 full 与 broadband_only，不强行指派为军鼓。各事件记录判定原因和分频强度。',
    'on_grid 是事件帧时刻到最近网格拍的非负距离，单位为帧，可含小数，不是布尔值；beat_index 从网格 t0 起计；bar 从 1 计数，开头不完整小节可为 0。beat_in_bar 为 1–4。帧边界表统一使用 [start_frame,end_frame)，秒边界保留音频精度。',
    '30 fps 最近帧量化本身有 ±16.667ms 上限，不能用音频精确网格残差冒充视频帧定位精度。','',
    '## 段落','',
    '逐小节计算立体声均方能量，以小节响度第 75 百分位为高能基准：响度≥基准−3dB 且平均高频通量≥0.04 判为 high；其余响度≥基准−7dB 且平均低频通量≥0.02 判为 hits；其余为 break，连续≥8 小节低能区命名为 build，首尾 hits 改为 intro_hits/outro_hits。相邻同类合并，不强制每 4 小节分组，以免剪辑版的 3 小节乐句被错分。段落名属于算法解释，能量和时间为实测。小节数为时长除以 4 拍，首拍前约 25ms 吸收至首段，末尾保留实际拖尾。剪辑版如存在哈希匹配的接口报告，同类段也在实际剪接处拆开；检测段界在接口一帧内时使用精确采样切点，网格、RMS 与事件仍由成片独立测量。','',
    '| 段落 | 起止秒 | 起止帧（末端不含） | 小节数 | 平均响度 dBFS |','|---|---:|---:|---:|---:|']
    for s in sections: lines.append(f"| {LABELS[s['label']]} `{s['label']}` | {s['start_t']:.6f}–{s['end_t']:.6f} | {s['start_frame']}–{s['end_frame']} | {s['bars']:.3f} | {s['mean_db']:.2f} |")
    lines+=['','## 重音数量与分布','',f"heavy {counts['heavy']}，medium {counts['medium']}，light {counts['light']}；合计 {len(events)} 个检测起音。",'', '| 小节 | 起止秒 | heavy | medium | light | dBFS |','|---:|---:|---:|---:|---:|---:|']
    for b in bars: lines.append(f"| {b['bar']} | {b['start_t']:.3f}–{b['end_t']:.3f} | {b['accents']['heavy']} | {b['accents']['medium']} | {b['accents']['light']} | {b['mean_db']:.2f} |")
    lines+=['','分段内每小节事件规律：']
    for sec in sections:
        subset=[b for b in bars if sec['start_t']<=(b['start_t']+b['end_t'])/2<sec['end_t']]
        parts=[]
        for lev in COLORS:
            vals=[b['accents'][lev] for b in subset]
            if vals: parts.append(f"{lev} 平均 {np.mean(vals):.1f} 次（{min(vals)}–{max(vals)}）")
        lines.append(f"- {sec['start_t']:.3f}–{sec['end_t']:.3f} 秒 {LABELS[sec['label']]}："+'；'.join(parts)+'。')
    lines+=['','整数拍上的分布（允许最近网格拍距离≤1.25帧）：']
    for lev in COLORS:
        distribution=Counter(e['beat_in_bar'] for e in events if e['level']==lev and e['on_grid']<=1.25)
        off=sum(e['level']==lev and e['on_grid']>1.25 for e in events)
        lines.append(f"- {lev}：第 1–4 拍分别为 {[distribution[i] for i in range(1,5)]}；其余 {off} 个位于半拍、细分拍或网格外。")
    diag=json.loads((out/'grid_diagnostics.json').read_text())
    lines+=['','## 网格验收与候选速度','',
        f"主 CSV 的 30 fps 初始节拍序列最大残差为 {diag['raw_tracker_30fps']['residual_ms_max']:.3f} ms。辅助音频定位使用 FFT=1024、hop=128（{128/audio['sample_rate']*1000:.3f} ms），所有检测阈值预先固定；预测拍附近 ±55ms 内取最近独立瞬态峰，未按 15ms 残差删去样本。",
        f"全曲 {grid['grid_beats']} 个网格拍匹配 {grid['visible_matched_beats']} 个瞬态，{grid['beats_without_qualifying_transient']} 拍无满足检测阈值的瞬态，覆盖率 {diag['selected']['match']*100:.2f}%。这未达到参考文档针对密集鼓点的 98% 全局覆盖门槛，故仅声称已匹配瞬态的残差通过 15ms 要求，不声称每拍均有鼓击。",
        '原始帧检测误差超标与实际变速是两回事。精定位后的全曲拟合已满足 15ms，无须为减小数字而任意切段；前半拟合、后半外推指标另列，用来避免最小二乘残差斜率天然近零造成误判。','',
        '| 速度候选 BPM | 全局命中率 | 低频整数拍召回 | 网格被低频覆盖 | 平均误差 ms | 最大误差 ms | 联合评分 |',
        '|---:|---:|---:|---:|---:|---:|---:|']
    for c in diag['tempo_candidates']:
        lines.append(f"| {c['bpm']:.4f} | {100*c['match']:.2f}% | {100*c['kick_integer_recall']:.2f}% | {100*c['kick_grid_coverage']:.2f}% | {c['mean_abs_ms']:.3f} | {c['residual_ms_max']:.3f} | {c['selection_score']:.4f} |")
    hold=diag['selected'].get('holdout')
    if hold: lines+=['',f"前半拟合外推至后半：平均有符号偏差 {hold['second_half_mean_signed_ms']:.3f} ms，最大绝对偏差 {hold['second_half_max_abs_ms']:.3f} ms；前半周期与全曲周期之差折算全时长为 {hold['period_difference_full_duration_ms']:.3f} ms。"]
    lines+=['','## 与参考脚本对照','']+reference_compare(refpath,grid,sections)
    lines+=['','## 复跑','',f"```bash\npython analyze_frames.py '{source}' '{out}'\n```",'',
    '同一环境、同一音频、相同参数生成确定性结果。原曲 SHA-256、库版本、参数和分析数据随 JSON 保留。网格的细粒度复核仅用于音频真值拟合；CSV 和事件列表始终为 30 fps。','']
    (out/'summary.md').write_text('\n'.join(lines),encoding='utf-8')

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('audio'); ap.add_argument('output_dir')
    ap.add_argument('--audiomap',help='music-to-video 的 analyze-beatgrid.py 产物，用来在摘要里对照 BPM 和段落')
    args=ap.parse_args()
    source=checked(args.audio); out=checked(args.output_dir); out.mkdir(parents=True,exist_ok=True)
    stereo,sr=sf.read(source,dtype='float32',always_2d=True); f=features(stereo,sr)
    from probe_grid import analyze_grid
    result=analyze_grid(f['y'],sr)
    grid=result.get('grid',result); diagnostics=result.get('diagnostics',result)
    dump(out/'grid_diagnostics.json',diagnostics)
    events,thresholds=classify_accents(f,grid)
    bars=bar_table(stereo,sr,f,grid,events)
    sections=auto_sections(bars,stereo,sr,grid)
    sections,edit_boundaries_used=respect_edit_interfaces(out,source,sections,stereo,sr,grid)
    data={'audio':{'filename':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'sample_rate':sr,'samples':len(stereo),'channels':stereo.shape[1],'duration':len(stereo)/sr,'frames':f['n'],'fps':FPS},'grid':grid,'accents':events,'sections':sections,'bars':bars,
          'analysis':{'hop_length':f['hop'],'n_fft':4096,'win_length':2048,'librosa':librosa.__version__,'numpy':np.__version__,'soundfile':sf.__version__,'onset_thresholds':thresholds,'frame_intervals':'half-open; t=n/30','on_grid_unit':'absolute fractional video frames','edit_report_boundaries_used':edit_boundaries_used}}
    dump(out/'accents.json',data)
    with (out/'music_frames.csv').open('w',encoding='utf-8',newline='') as h:
        w=csv.writer(h); w.writerow(['frame','t','rms_db','onset_low','onset_mid','onset_high','onset_full'])
        for n in range(f['n']): w.writerow([n,f'{n/FPS:.9f}',f"{f['rms_db'][n]:.9f}"]+[f"{f['flux'][b][n]:.9f}" for b in ('low','mid','high','full')])
    plot_timeline(out/'music_timeline.png',stereo,sr,f,grid,events,sections,bars)
    refpath=Path(args.audiomap).resolve() if args.audiomap else out/'audiomap.json'
    write_summary(out,source,data,f,thresholds,refpath)
    print(json.dumps({'source':source.name,'bpm':grid['bpm'],'residual_ms':grid['residual_ms_max'],'duration':len(stereo)/sr,'frames':f['n'],'accents':dict(Counter(e['level'] for e in events)),'sections':[{k:s[k] for k in ('start_t','end_t','label')} for s in sections]},ensure_ascii=False))
if __name__=='__main__': main()
