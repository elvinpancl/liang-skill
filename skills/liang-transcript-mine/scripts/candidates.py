#!/usr/bin/env python3
"""校验子代理写出的候选，按目标卡/条/节分组成工作清单。

用法：
  candidates.py validate [--run DIR] [--only Q004[,Q005…]]   逐行校验 <运行目录>/候选/*.jsonl，只打印问题
  candidates.py group    [--run DIR]   生成 <运行目录>/工作清单.md，只打印统计

字段定义见 references/candidate_schema_脱敏版.md。
"""
import argparse, json, re, sys
from collections import defaultdict
from pathlib import Path
from card_locator import parse
from common import KIND_ZH, RUN_STATE_NAME, ROOT, in_run, load_json, master_drift, master_path, rel, resolve_run, short

REQUIRED = ["id", "source", "lines", "who", "problem", "advice", "why", "nature",
            "target_kind", "disposition", "reason"]
DISPOSITIONS = {"已覆盖", "值得补充", "新内容", "不入库", "待补材料"}
NATURES = {"连麦建议", "讲者观点", "讲者自述", "他述案例", "实测结果", "方法演示"}
KINDS = {"tactics", "insights", "method", "none"}
LABELS = {"判断", "逻辑", "边界", "动作", "怎么讲"}
# 写作者提醒不进正文（契约「先读完整的事」一节）
SELF_TALK = re.compile(r"原转写|本次改写|不补造|不冒充|口径不清|未完整给|待问|未知")
# 契约「边界只写一次」：段末已有〔标签〕又写「不能……」是双重限定；「不能把 X 写成 Y」是写给作者的禁令
TAG = re.compile(r"〔[^〕]{1,20}〕")
HEDGE = re.compile(r"(?<!能)不能|不等于|不代表")
AUTHOR_BAN = re.compile(r"不能把[^。；]{0,40}?(?:写成|当成|当作|算成|说成)|不能据此|据此认定|不能直接当")


def load_units(run):
    """按开轮快照的母版校验目标，与子代理定位时用的是同一份。"""
    cache = {}
    for k in ("tactics", "insights", "method"):
        lines = master_path(k, run=run).read_text(encoding="utf-8").split("\n")
        cache[k] = {u["id"]: u for u in parse(k, lines)}
    return cache


def check(c, units):
    errs, warns = [], []
    for f in REQUIRED:
        if c.get(f) in (None, "", []):
            errs.append(f"缺 {f}")
    if c.get("disposition") not in DISPOSITIONS:
        errs.append(f"disposition 只能是 {sorted(DISPOSITIONS)}")
    if c.get("nature") not in NATURES:
        errs.append(f"nature 只能是 {sorted(NATURES)}")
    kind = c.get("target_kind")
    if kind not in KINDS:
        errs.append(f"target_kind 只能是 {sorted(KINDS)}")
    lines = c.get("lines")
    if not (isinstance(lines, list) and len(lines) == 2 and all(isinstance(x, int) for x in lines) and lines[0] <= lines[1]):
        errs.append("lines 应为 [起, 止] 两个整数")
    if kind in ("tactics", "insights", "method"):
        tid, sub = c.get("target_id"), c.get("target_sub")
        if tid == "new":
            if not c.get("new_title"):
                errs.append("target_id=new 时要给 new_title")
        elif tid not in units[kind]:
            errs.append(f"{KIND_ZH[kind]} {tid} 不存在")
        if kind == "tactics" and tid != "new" and sub not in range(1, 8):
            errs.append("打法候选要给 target_sub 1-7（模块号）")
        if kind == "insights" and sub is not None and sub not in LABELS:
            errs.append(f"洞见 target_sub 应为 {sorted(LABELS)} 之一或留空")
    disp = c.get("disposition")
    if disp in ("值得补充", "新内容") and not c.get("draft"):
        errs.append("值得补充 / 新内容 要给 draft（正文草稿）")
    if disp == "已覆盖" and not c.get("covered_by"):
        errs.append("已覆盖 要写 covered_by（如 卡1·模块5 L163）")
    if disp == "待补材料" and not c.get("missing"):
        errs.append("待补材料 要写 missing：缺什么、可能从哪里补；补不到的判 不入库 或 已覆盖")
    if c.get("draft"):
        hits = sorted(set(SELF_TALK.findall(c["draft"])))
        if hits:
            warns.append(f"draft 含写作者提醒用语 {hits}，移到 ledger_note")
        if TAG.search(c["draft"]) and HEDGE.search(c["draft"]):
            warns.append("draft 段末已有〔标签〕又写了「不能／不等于／不代表」，只留一处；条件会改变读者决定时写成读者动作")
        if AUTHOR_BAN.search(c["draft"]):
            warns.append("draft 有写给作者的禁令句（如「不能把 X 写成 Y」「不能据此认定」），删去或改成读者要做的事")
    if c.get("quote") and len(c["quote"]) > 120:
        warns.append("quote 超过 120 字，只留最有用的一句")
    return errs, warns


def read_all(run, only=None):
    out = []
    ids = [x.strip() for x in (only or "").split(",") if x.strip()]
    files = [run / "候选" / f"{x}.jsonl" for x in ids] if ids else sorted((run / "候选").glob("*.jsonl"))
    for f in files:
        if not f.exists():
            out.append((f.name, 0, {"_parse_error": "文件不存在"}))
            continue
        for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not ln.strip():
                continue
            try:
                out.append((f.name, n, json.loads(ln)))
            except json.JSONDecodeError as e:
                out.append((f.name, n, {"_parse_error": str(e)}))
    return out


def cmd_validate(args):
    run = resolve_run(args.run)
    units = load_units(run)
    rows = read_all(run, args.only)
    bad = warn = 0
    seen = set()
    for fname, n, c in rows:
        if "_parse_error" in c:
            print(f"{fname}:{n} JSON 解析失败：{c['_parse_error']}")
            bad += 1
            continue
        errs, warns = check(c, units)
        if c.get("id") in seen:
            errs.append(f"id 重复 {c['id']}")
        seen.add(c.get("id"))
        for e in errs:
            print(f"{fname}:{n} 错误 {e}")
        for w in warns:
            print(f"{fname}:{n} 提醒 {w}")
        bad += bool(errs)
        warn += bool(warns)
    files = len({f for f, _, _ in rows})
    print(f"候选 {len(rows)} 条（{files} 个文件）｜错误 {bad} 条｜提醒 {warn} 条")
    return 1 if bad else 0


def cmd_group(args):
    run = resolve_run(args.run)
    units = load_units(run)
    rows = [c for _, _, c in read_all(run) if "_parse_error" not in c]
    drift = master_drift(run)
    groups = defaultdict(list)
    stat = defaultdict(int)
    for c in rows:
        stat[c.get("disposition")] += 1
        if c.get("disposition") in ("已覆盖", "不入库"):
            continue
        kind = c.get("target_kind")
        groups[(kind, str(c.get("target_id")), str(c.get("target_sub") or ""))].append(c)

    def title(kind, tid):
        if kind == "none":
            return "无处安放（只进台账）"
        if tid == "new":
            return "新建"
        u = units.get(kind, {}).get(int(tid)) if tid.isdigit() else None
        return u["title"] if u else "?"

    order = {"tactics": 0, "insights": 1, "method": 2, "none": 3}
    keys = sorted(groups, key=lambda k: (order.get(k[0], 9), int(k[1]) if k[1].isdigit() else 10**6, k[2]))
    md = [f"# 工作清单｜{rel(run)}", "",
          "按目标位置分组；已覆盖、不入库的只计数不列出，它们照样进案例库。合并时先用 card_locator.py get 读整张卡/整条洞见，再把新材料融进去，不在末尾贴段。", ""]
    stale_carry = carried_drift(run, rows)
    if stale_carry:
        md += ["> 以下沿用候选来自母版快照不同的候选周：" + "、".join(stale_carry)
               + "。合并前按编号在本轮母版里重新核对去向。", ""]
    if drift:
        md += ["> 开轮后正式母版已换版：" + "；".join(f"{KIND_ZH[k]} {Path(a).name} → {Path(b).name}" for k, a, b in drift)
               + "。卡号、洞见号按契约保持不变，合并前在新母版里按编号重新取段核对，模块内容可能已改写。", ""]
    for kind, tid, sub in keys:
        name = KIND_ZH.get(kind, "其他")
        head = f"## {name} {tid}｜{title(kind, tid)}" + (f"｜{'模块' if kind == 'tactics' else ''}{sub}" if sub else "")
        md.append(head)
        for c in groups[(kind, tid, sub)]:
            md.append(f"- **{c['id']}**〔{c['disposition']}｜{c['nature']}〕{c['source']} L{c['lines'][0]}-{c['lines'][1]}")
            if c.get("new_title"):
                md.append(f"  - 拟新标题：{c['new_title']}")
            md.append(f"  - 谁／问题：{c['who']}；{c['problem']}")
            md.append(f"  - 建议／为什么：{c['advice']}；{c['why']}")
            if c.get("quote"):
                md.append(f"  - 原话：「{c['quote']}」")
            if c.get("draft"):
                md.append(f"  - 草稿：{c['draft']}")
            if c.get("covered_by"):
                md.append(f"  - 已出现在：{c['covered_by']}（合并时避免重复写入）")
            if c.get("missing"):
                md.append(f"  - 缺什么：{c['missing']}")
            md.append(f"  - 去向理由：{c['reason']}")
            if c.get("ledger_note"):
                md.append(f"  - 台账：{c['ledger_note']}")
        md.append("")
    out = run / "工作清单.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"候选 {len(rows)} 条：" + "，".join(f"{k} {v}" for k, v in sorted(stat.items())))
    print(f"涉及 {len(keys)} 个目标位置；工作清单：{rel(out)}")
    for k, a, b in drift:
        print(f"注意：{KIND_ZH[k]}母版开轮后已换版 {Path(a).name} → {Path(b).name}，合并前按编号在新版重新核对")
    carried = sorted({c["carried_from"] for c in rows if c.get("carried_from")})
    if carried:
        print(f"其中沿用候选周的来源 {len(carried)} 份" + (f"；母版快照不同：{'、'.join(stale_carry)}" if stale_carry else ""))
    for kind, tid, sub in keys[:8]:
        print(f"  {KIND_ZH.get(kind, '其他')} {tid}{('·' + sub) if sub else ''} {short(title(kind, tid), 20)}：{len(groups[(kind, tid, sub)])} 条")
    if len(keys) > 8:
        print(f"  …其余 {len(keys) - 8} 个位置见工作清单")
    return 0


def carried_drift(run, rows):
    """沿用候选来自哪个候选周；那一轮的母版快照和本轮不同，就要按编号重核去向。"""
    now = {k: v.get("sha256") for k, v in (load_json(run / RUN_STATE_NAME, {}).get("masters") or {}).items()}
    out = []
    for src in sorted({c["carried_from"].rsplit("/", 1)[0] for c in rows if c.get("carried_from")}):
        old = load_json(in_run(ROOT / src, RUN_STATE_NAME), {}).get("masters") or {}
        if any(isinstance(v, dict) and v.get("sha256") != now.get(k) for k, v in old.items()):
            out.append(src)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "group"):
        p = sp.add_parser(name); p.add_argument("--run")
        if name == "validate":
            p.add_argument("--only", help="只校验某几个来源，如 Q004 或 Q038,Q039")
    args = ap.parse_args()
    return {"validate": cmd_validate, "group": cmd_group}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
