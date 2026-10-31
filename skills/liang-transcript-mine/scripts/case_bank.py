#!/usr/bin/env python3
"""把每轮提取出的完整案例整理成本地案例库，供选题、直播答疑和客户沟通时找例子。不改三库、不发飞书。

用法：
  case_bank.py build [--since YYYY-MM-DD]   扫描运行目录，重建 直播录音资料/案例库/ 下三份 Markdown 和 制作过程/cases.jsonl

三库只收新判断，判「已覆盖」的完整故事以前只留在过程 JSON 里，这里把它们都收进来。
案例取自子代理写的 候选/*.jsonl（字段统一），再叠加主线程裁定：裁定/<QID>.json（数组，带 decision、
decision_reason），或旧格式的 候选最终裁定.json（带 decision、reason、target）。运行收尾时常把
过程文件挪进 制作过程/，两处都找。同一来源以最近一次提取为准（整篇重读过，旧的那批作废；发布周沿用的候选
也算最近一次）；裁定为重复来源的不收。短稿里几个案例常共用同一行号范围，所以不按行号去重。
每次全量重建，结果只取决于运行目录里的文件，可以随时重跑。
"""
import argparse, json, re, sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from card_locator import parse
from common import CONFIG, ROOT, SCRATCH, dump_json, in_run, load_json, master_path, rel, short

OUT = ROOT / "案例库"
FILES = {
    "tactics": ("打法案例_改写版.md", "打法案例库",
                "直播和短视频里的完整问答和案例，按打法卡分组。找某个行业的真实例子、开头素材或客户常见卡点时用。"),
    "insights": ("洞见案例_改写版.md", "洞见案例库",
                 "按商业洞见分组的完整案例。讲一个判断时，从这里挑一个具体的人和事来讲。"),
    "other": ("方法与其他案例_改写版.md", "方法与其他案例库",
              "按诊断方法分组的案例；后半部分是没定到三库具体位置的案例（材料不全，或是个人选择、家庭、情感等话题），按讲者分组。"),
}
SPEAKERS = list(CONFIG.get("speaker_aliases", {}))
ALIAS = CONFIG.get("speaker_aliases", {})
DIR_SPEAKERS = list(CONFIG.get("speaker_paths", {}).items())


def speaker(path):
    name = Path(path).name
    for k in SPEAKERS:
        if name.startswith(k):
            return ALIAS.get(k, k)
    head = re.split(r"[：:]", name, maxsplit=1)[0]
    if head != name and 1 <= len(head) <= 4:
        return head
    for key, who in DIR_SPEAKERS:
        if key in path:
            return who
    return "其他"


def source_date(path, run_day):
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", path)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"/(\d{2})\.(\d{1,2})\.(\d{1,2})\s*_原文", path)  # 兼容 YY.MM.DD_原文.docx 日期写法
    if m:
        return f"20{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"/抖音研究/(\d{4}-\d{2}-\d{2})/", path)
    return m.group(1) if m else run_day


def runs_since(since):
    out = []
    for d in sorted(SCRATCH.glob("增量挖掘_*/运行_*")):
        day = d.parent.name.split("_", 1)[1][:10]
        cdir = in_run(d, "候选")
        if day >= since and cdir.is_dir() and any(cdir.glob("*.jsonl")):
            out.append((day, d))
    return out


def verdicts(run):
    """主线程裁定：新格式 裁定/<QID>.json；旧格式 候选最终裁定.json。"""
    out = {}
    vdir = in_run(run, "裁定")
    if vdir.is_dir():
        for f in sorted(vdir.glob("*.json")):
            data = load_json(f, [])
            for v in data if isinstance(data, list) else []:
                if isinstance(v, dict) and v.get("id"):
                    out[v["id"]] = dict(decision=v.get("decision"), decision_reason=v.get("decision_reason"))
    old = in_run(run, "候选最终裁定.json")
    if old.exists():
        for v in load_json(old, []):
            if isinstance(v, dict) and v.get("id"):
                t = v.get("target")
                out.setdefault(v["id"], dict(decision=v.get("decision"), decision_reason=v.get("reason"),
                                             final_target=None if t in (None, "", "候选台账") else t))
    return out


def where(c):
    k, tid, sub = c.get("target_kind"), c.get("target_id"), c.get("target_sub")
    if k == "tactics":
        return f"打法 {tid}" + (f"·模块 {sub}" if sub else "")
    if k == "insights":
        return f"洞见 {tid}" + (f"·{sub}" if sub else "")
    if k == "method":
        return f"方法 {tid}"
    return "三库外"


def status(c):
    d = c.get("decision")
    why = short(c.get("decision_reason") or c.get("reason") or "", 80)
    if d == "采用":
        return f"已写入{c.get('final_target') or where(c)}"
    if d == "已覆盖":
        return f"同类已在{c.get('covered_by') or where(c)}"
    if d == "待补材料":
        return f"缺材料，暂未写入：{why}"
    if d in ("不采用", "不入库", "不纳正文"):
        return f"未入三库：{why}"
    if d is None:
        return f"待发布周裁定（提取时判为{c.get('disposition')}）"
    return f"{d}：{why}"


def category(c):
    d = c.get("decision")
    if d is None:
        return "待裁定"
    return {"采用": "已写入三库", "已覆盖": "同类已有", "待补材料": "缺材料",
            "不采用": "未入三库", "不入库": "未入三库", "不纳正文": "未入三库"}.get(d, d)


def bucket(c):
    k, tid = c.get("target_kind"), c.get("target_id")
    if k in ("tactics", "insights") and (isinstance(tid, int) or tid == "new"):
        return k, tid
    if k == "method" and isinstance(tid, int):
        return "method", tid
    return "none", c["speaker"]  # 没定位置的案例按讲者分组，免得几百条堆在一个标题下


def origin_verdict(c, cache):
    """沿用来的候选在本轮还没裁定时，带上它原来那一轮的裁定。"""
    src, _, old = str(c.get("carried_from") or "").rpartition("/")
    if not src:
        return {}
    if src not in cache:
        cache[src] = verdicts(ROOT / src)
    return cache[src].get(re.sub(r"^Q\d+-", f"{old}-", str(c.get("id", ""))), {})


def collect(since):
    by_source, seen_runs, origin = {}, [], {}
    for day, run in runs_since(since):
        vs = verdicts(run)
        batch = defaultdict(list)
        for f in sorted(in_run(run, "候选").glob("*.jsonl")):
            for ln in f.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                try:
                    c = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                c.update(vs.get(c.get("id")) or origin_verdict(c, origin))
                src = str(c.get("source") or "")
                c.update(run=rel(run), run_day=day, speaker=speaker(src), date=source_date(src, day))
                c["category"] = category(c)
                batch[src].append(c)
        by_source.update(batch)  # 后面的轮次整篇覆盖前面的
        seen_runs.append((day, rel(run), sum(len(v) for v in batch.values())))
    cases = [c for rows in by_source.values() for c in rows
             if c.get("decision") != "重复来源" and len(str(c.get("advice") or "")) >= 6]
    return cases, seen_runs  # 去掉同场重复的另一份转写，和「整篇无可用内容」的说明行


def entry(c):
    tag = "｜".join(x for x in (c["speaker"], c["date"], c.get("nature")) if x)
    out = [f"### {short(str(c.get('who') or '（未写来访者）'), 40)}", f"〔{tag}〕", ""]
    for label, key in (("问题", "problem"), ("建议", "advice"), ("为什么", "why")):
        if c.get(key):
            out.append(f"- **{label}：** {c[key]}")
    if c.get("quote"):
        out.append(f"- **原话：** 「{str(c['quote']).strip('「」')}」")
    if c.get("new_title"):
        out.append(f"- **拟新建：** {c['new_title']}")
    out.append(f"- **三库：** {status(c)}")
    src = str(c.get("source") or "")
    a, b = (list(c.get("lines") or []) + [0, 0])[:2]
    out.append(f"- **来源：** [{Path(src).name}](<{(ROOT / src).resolve()}>) 第 {a}–{b} 行")
    out.append("")
    return out


def render(name, groups, titles):
    fname, title, desc = FILES[name]
    keys = sorted(groups, key=lambda k: ({"tactics": 0, "insights": 0, "method": 1, "none": 2}[k[0]],
                                        k[1] if isinstance(k[1], int) else 10**6,
                                        -len(groups[k]) if k[0] == "none" else 0))
    n = sum(len(v) for v in groups.values())
    md = [f"# {title}（更新至 {datetime.now().astimezone():%Y-%m-%d}）", "", f"> {desc}",
          "> 「三库」一行说明它和正式库的关系：已写入、同类已有、缺材料或未入库。案例是讲者在连麦或视频里的建议和"
          "来访者自述，结果多数没有回访。对外使用前，去掉能认出具体人的细节（城市加年龄、店名、金额组合等）。", "",
          f"共 {n} 条，分在 {len(keys)} 个位置下；同一位置里新的在前。由 `case_bank.py build` 从 2026 年 10 月 12 日"
          "以来各轮的提取记录重建，数据在 [制作过程/cases.jsonl](制作过程/cases.jsonl)。", ""]
    for k in keys:
        kind, tid = k
        if kind == "none":
            head = f"## 未定位置的案例｜{tid}"
        elif tid == "new":
            head = f"## 拟新建的{'行业' if kind == 'tactics' else '洞见'}"
        elif kind == "tactics":
            head = f"## {tid}｜{titles[kind].get(tid, '（卡号不在当前母版）')}"
        elif kind == "insights":
            head = f"## 洞见 {tid:02d}｜{titles[kind].get(tid, '（编号不在当前母版）')}"
        else:
            head = f"## 方法 {tid}｜{titles[kind].get(tid, '（节号不在当前母版）')}"
        md += [f"{head}（{len(groups[k])} 条）", ""]
        for c in sorted(groups[k], key=lambda c: (c["date"], c["run_day"]), reverse=True):
            md += entry(c)
    (OUT / fname).write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    return fname, n, len(keys)


def cmd_build(args):
    titles = {k: {u["id"]: u["title"] for u in parse(k, master_path(k).read_text(encoding="utf-8").split("\n"))}
              for k in ("tactics", "insights", "method")}
    cases, seen = collect(args.since)
    if not cases:
        print(f"{args.since} 以来的运行目录里没有候选，案例库未改动")
        return 1
    files = {"tactics": defaultdict(list), "insights": defaultdict(list), "other": defaultdict(list)}
    for c in cases:
        k = bucket(c)
        files["other" if k[0] in ("method", "none") else k[0]][k].append(c)
    OUT.mkdir(exist_ok=True)
    (OUT / "制作过程").mkdir(exist_ok=True)
    with (OUT / "制作过程" / "cases.jsonl").open("w", encoding="utf-8") as fh:
        for c in sorted(cases, key=lambda c: (c["run_day"], str(c.get("id")))):
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    for name, groups in files.items():
        fname, n, g = render(name, groups, titles)
        print(f"{fname}：{n} 条，{g} 个位置")
    st = Counter(c["category"] for c in cases)
    print(f"共 {len(cases)} 条｜" + "，".join(f"{k} {v}" for k, v in st.most_common()))
    print("按讲者：" + "，".join(f"{k} {v}" for k, v in Counter(c["speaker"] for c in cases).most_common(8)))
    print("取自：" + "；".join(f"{d} {r.split('/')[-1]} {n} 条" for d, r, n in seen))
    print(f"案例库：{rel(OUT)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("build"); p.add_argument("--since", default=str(CONFIG.get("carry_since", "0000-00-00")), help="只收这一天及以后的运行")
    args = ap.parse_args()
    return {"build": cmd_build}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
