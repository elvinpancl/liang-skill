#!/usr/bin/env python3
"""按卡号 / 洞见号 / 方法节读取母版片段，不把整份母版放进上下文。

kind：tactics（打法，### N. 卡 → #### 1-7 模块）
      insights（洞见，#### 洞见 NN｜ → ##### 子块；--label 取五个标签段）
      method（方法，## 节，按出现顺序编号 1..n）

用法：
  card_locator.py verify  --kind tactics                 结构核验：编号连续、模块齐全有序、分段覆盖全文
  card_locator.py find    --kind tactics 餐饮 民宿        在卡/条/节标题里找关键词
  card_locator.py grep    --kind insights '提价' [--max 15]  正文检索，返回所在单元与一行摘录
  card_locator.py get     --kind tactics --id 1 --sub 5   只输出第 1 卡模块 5
  card_locator.py get     --kind insights --id 36 --label 边界
  card_locator.py list    --kind method                  列出单元编号、标题、行范围
  card_locator.py probe   --run R '示例行业&交付&咨询' '示例服务&边界'   一次查完多个案例：
                          每组 & 连接应同时出现的词，按同一模块命中几个词排序
  card_locator.py getmany --run R t1:4 i1:逻辑 m1      一次取多个位置（t 打法卡:模块，i 洞见:标签，m 方法节）
通用参数：--run 按该运行目录开轮时固定的母版快照定位（提取和校验时都要给）；
          --file 指定其他稿件；两者都不给时读 SOURCE_OF_TRUTH 当前登记的正式母版。
"""
import argparse, re, sys
from common import KIND_ZH, master_path, rel, short

HEADING = re.compile(r"^(#{1,6}) ")
SPECS = {
    "tactics": dict(unit=re.compile(r"^### (\d+)\. (.+)$"), level=3,
                    sub=re.compile(r"^#### ([1-7])\. (.+)$"), sub_level=4),
    "insights": dict(unit=re.compile(r"^#### 洞见 (\d+)｜(.+)$"), level=4,
                     sub=re.compile(r"^##### (.+)$"), sub_level=5),
    "method": dict(unit=re.compile(r"^## (.+)$"), level=2,
                   sub=re.compile(r"^### (.+)$"), sub_level=3),
}
LABELS = ("判断", "逻辑", "边界", "动作", "怎么讲")
# 两种写法都认：V10 起的「##### **判断**」小标题，以及旧版的「**判断：**」「- **判断**：」加粗段落
LABEL_RE = re.compile(r"^(?:#{5}\s+\*\*(" + "|".join(LABELS) + r")\*\*\s*$|\s*(?:-\s*)?\*\*(" + "|".join(LABELS)
                      + r")(?:：\*\*|\*\*：))")


def label_of(line):
    m = LABEL_RE.match(line)
    return (m.group(1) or m.group(2)) if m else None
TACTIC_MODULES = ["这门生意现在怎么打", "用户分析", "客户为什么会买", "不同情况分别做什么内容",
                  "直接拍什么、怎么拍", "流量来了怎么接", "第一轮怎么验证"]
ALT_MODULE7 = "执行与验证"  # 少数旧卡的第 7 模块标题


def heading_level(line):
    m = HEADING.match(line)
    return len(m.group(1)) if m else None


def trim_end(lines, start, end):
    """把单元尾部的空行和下一单元的 <a id> 锚点让出去。"""
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("<a id=")):
        end -= 1
    return end


def parse(kind, lines):
    spec = SPECS[kind]
    levels = []
    fence = False
    for ln in lines:
        if ln.startswith("```"):
            fence = not fence
        levels.append(None if fence else heading_level(ln))

    units = []
    ordinal = 0
    for i, ln in enumerate(lines):
        if levels[i] != spec["level"]:
            continue
        m = spec["unit"].match(ln)
        if not m:
            continue
        ordinal += 1
        if kind == "method":
            uid, title = ordinal, m.group(1)
        else:
            uid, title = int(m.group(1)), m.group(2)
        end = next((j for j in range(i + 1, len(lines)) if levels[j] and levels[j] <= spec["level"]), len(lines))
        units.append(dict(id=uid, title=title.strip(), start=i, end=trim_end(lines, i, end), subs=[]))

    for u in units:
        starts = [j for j in range(u["start"] + 1, u["end"])
                  if levels[j] == spec["sub_level"] and spec["sub"].match(lines[j])]
        if kind == "insights" and (not starts or starts[0] > u["start"] + 1):
            first = starts[0] if starts else u["end"]
            u["subs"].append(dict(id=0, title="正文", start=u["start"], end=trim_end(lines, u["start"], first)))
        for n, j in enumerate(starts):
            nxt = next((k for k in range(j + 1, u["end"]) if levels[k] and levels[k] <= spec["sub_level"]), u["end"])
            m = spec["sub"].match(lines[j])
            if kind == "tactics":
                sid, title = int(m.group(1)), m.group(2)
            else:
                sid, title = n + 1, m.group(1)
            u["subs"].append(dict(id=sid, title=title.strip().strip("*").strip(), start=j, end=trim_end(lines, j, nxt)))
    return units


def load(args):
    path = master_path(args.kind, args.file, getattr(args, "run", None))
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    return path, lines, parse(args.kind, lines)


def locate(units, line_no):
    """给 0 起的行号返回 (单元, 子块)。"""
    for u in units:
        if u["start"] <= line_no < u["end"]:
            sub = next((s for s in u["subs"] if s["start"] <= line_no < s["end"]), None)
            return u, sub
    return None, None


def tag(kind, u, s=None):
    name = {"tactics": "卡", "insights": "洞见", "method": "方法节"}[kind]
    t = f"{name}{u['id']}"
    if s is not None:
        if kind == "insights" and s["title"] in LABELS:
            t += f"·{s['title']}"
        else:
            t += f"·{'模块' if kind == 'tactics' else '子块'}{s['id']}"
    return t


def cmd_verify(args):
    path, lines, units = load(args)
    problems = []
    ids = [u["id"] for u in units]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        problems.append(f"编号重复：{dup[:10]}")
    if args.kind != "method" and ids and sorted(ids) != list(range(min(ids), max(ids) + 1)):
        missing = sorted(set(range(min(ids), max(ids) + 1)) - set(ids))
        problems.append(f"编号不连续，缺：{missing[:10]}")
    module_total = 0
    if args.kind == "tactics":
        for u in units:
            got = [s["id"] for s in u["subs"]]
            module_total += len(got)
            if got != list(range(1, 8)):
                problems.append(f"卡{u['id']} 模块顺序为 {got}")
                continue
            for s in u["subs"]:
                want = TACTIC_MODULES[s["id"] - 1]
                if s["title"] != want and not (s["id"] == 7 and s["title"] == ALT_MODULE7):
                    problems.append(f"卡{u['id']} 模块{s['id']} 标题「{s['title']}」≠「{want}」")
    if args.kind == "insights":
        for u in units:
            body = lines[u["start"]:u["end"]]
            found = [lb for lb in map(label_of, body) if lb]
            lack = [l for l in LABELS if l not in found]
            dup = sorted({l for l in found if found.count(l) > 1})
            if lack:
                problems.append(f"洞见{u['id']} 缺标签 {lack}")
            if dup:
                problems.append(f"洞见{u['id']} 标签重复 {dup}（契约要求每条只有一套）")
    # 分段覆盖：单元之间不重叠
    for a, b in zip(units, units[1:]):
        if a["end"] > b["start"]:
            problems.append(f"{tag(args.kind, a)} 与 {tag(args.kind, b)} 行范围重叠")
    print(f"{KIND_ZH[args.kind]}：{rel(path)}｜{len(lines)} 行｜单元 {len(units)}"
          + (f"｜模块 {module_total}" if args.kind == "tactics" else "")
          + (f"｜编号 {min(ids)}–{max(ids)}" if ids and args.kind != "method" else ""))
    print(f"问题 {len(problems)} 处" + ("" if not problems else "，前 10 处："))
    for p in problems[:10]:
        print(f"  - {p}")
    return 1 if problems else 0


def cmd_list(args):
    path, lines, units = load(args)
    lo, hi = (int(x) for x in args.range.split("-")) if args.range else (None, None)
    for u in units:
        if lo is not None and not (lo <= u["id"] <= hi):
            continue
        print(f"{u['id']}\t{u['title']}\tL{u['start']+1}-{u['end']}")


def cmd_find(args):
    path, lines, units = load(args)
    kws = args.keywords
    hits = [u for u in units if any(k in u["title"] for k in kws)]
    for u in hits[: args.max]:
        print(f"{tag(args.kind, u)}\t{u['title']}")
    if len(hits) > args.max:
        print(f"…另有 {len(hits) - args.max} 个，加关键词收窄")
    if not hits:
        print("标题无命中；改用 grep 搜正文")


def cmd_grep(args):
    path, lines, units = load(args)
    pat = re.compile(args.pattern)
    n = 0
    for i, ln in enumerate(lines):
        if not pat.search(ln):
            continue
        u, s = locate(units, i)
        where = tag(args.kind, u, s) if u else "卡外"
        m = pat.search(ln)
        a = max(0, m.start() - 30)
        print(f"{where}\tL{i+1}\t{short(ln[a:a + args.width], args.width)}")
        n += 1
        if n >= args.max:
            print(f"…已达 --max {args.max}，收窄正则或加大 --max")
            break
    if n == 0:
        print("无命中")


def extract(kind, lines, units, uid, sub=None, label=None):
    """返回 (标注, 标题, 起行, 止行, 正文) 或 (错误信息, None, ...)。"""
    u = next((x for x in units if x["id"] == uid), None)
    if not u:
        return f"没有 {KIND_ZH[kind]} {uid}", None, 0, 0, ""
    start, end, name = u["start"], u["end"], tag(kind, u)
    if sub is not None:
        s = next((x for x in u["subs"] if x["id"] == sub), None)
        if not s:
            return f"{name} 没有子块 {sub}；可选：{[(x['id'], x['title']) for x in u['subs']]}", None, 0, 0, ""
        start, end, name = s["start"], s["end"], tag(kind, u, s)
    body = lines[start:end]
    if label:
        kept, on = [], False
        for i in range(start, end):
            lb = label_of(lines[i])
            if lb:
                on = lb == label
            elif heading_level(lines[i]):
                on = False
            if on:
                kept.append(i)
        body = [lines[i] for i in kept]
        if kept:
            start, end = kept[0], kept[-1] + 1
        name += f"·{label}"
    return name, u["title"], start, end, "\n".join(body)


def show(name, title, start, end, text, max_chars):
    print(f"〔{name}｜{title}｜L{start+1}-{end}｜{len(text)} 字〕")
    if len(text) > max_chars:
        print(text[:max_chars])
        print(f"〔已截断，余 {len(text) - max_chars} 字；缩小范围或加大 --max-chars〕")
    else:
        print(text)


def cmd_get(args):
    path, lines, units = load(args)
    name, title, start, end, text = extract(args.kind, lines, units, args.id, args.sub, args.label)
    if title is None:
        print(name)
        return 1
    show(name, title, start, end, text, args.max_chars)


KIND_PREFIX = {"t": "tactics", "i": "insights", "m": "method"}


def load_kind(kind, args):
    path = master_path(kind, None, getattr(args, "run", None))
    lines = path.read_text(encoding="utf-8").split("\n")
    return lines, parse(kind, lines)


def cmd_getmany(args):
    """一次取多个位置：t202:4（卡 202 模块 4）、i90:逻辑（洞见 90 的逻辑）、i90（整条）、m5（方法第 5 节）。"""
    cache, bad = {}, 0
    for item in args.items:
        m = re.fullmatch(r"([tim])(\d+)(?::(.+))?", item)
        if not m:
            print(f"〔{item}：格式应为 t202:4 / i90:逻辑 / m5〕")
            bad += 1
            continue
        kind, uid, rest = KIND_PREFIX[m.group(1)], int(m.group(2)), m.group(3)
        if kind not in cache:
            cache[kind] = load_kind(kind, args)
        lines, units = cache[kind]
        sub = label = None
        if rest:
            if rest in LABELS:
                label = rest
            elif rest.isdigit():
                sub = int(rest)
            else:
                print(f"〔{item}：冒号后应为模块号、子块号或标签〕")
                bad += 1
                continue
        name, title, start, end, text = extract(kind, lines, units, uid, sub, label)
        if title is None:
            print(f"〔{name}〕")
            bad += 1
            continue
        show(name, title, start, end, text, args.max_chars)
        print()
    return 1 if bad else 0


def blocks(kind, units):
    """probe 的比对粒度：打法按模块，洞见按标签段或子块，方法按节内小节（没有就整节）。"""
    for u in units:
        subs = [x for x in u["subs"] if x["end"] > x["start"]]
        if subs:
            for x in subs:
                yield u, x, x["start"], x["end"]
        else:
            yield u, None, u["start"], u["end"]


def cmd_probe(args):
    """一次查完多个案例。每组用 & 连接应同时出现的词，组内同义写法用 |。
    按「同一模块里命中几个词」排序，命中最全的排最前，避免被文件前部的零散命中挤掉。"""
    kinds = list(KIND_PREFIX.values()) if args.kind == "all" else [args.kind]
    data = {k: load_kind(k, args) for k in kinds}
    for gi, group in enumerate(args.groups, 1):
        terms = [re.compile(t) for t in group.split("&") if t]
        print(f"【{gi}】{group}")
        shown = 0
        for k in kinds:
            lines, units = data[k]
            titles = [u for u in units if any(t.search(u["title"]) for t in terms)][:2]
            for u in titles:
                print(f"  标题 {tag(k, u)}｜{short(u['title'], 30)}")
                shown += 1
            scored = []
            for order, (u, sub, a, b) in enumerate(blocks(k, units)):
                text = "\n".join(lines[a:b])
                hit = [t for t in terms if t.search(text)]
                if hit:
                    first = min(t.search(text).start() for t in hit)
                    line_no = a + text.count("\n", 0, first) + 1
                    ln = lines[line_no - 1]
                    mm = next((t.search(ln) for t in hit if t.search(ln)), None)
                    col = max(0, mm.start() - 20) if mm else 0
                    scored.append((-len(hit), order, u, sub, line_no, ln[col:col + args.width]))
            scored.sort(key=lambda x: (x[0], x[1]))
            need = 1 if len(terms) <= 2 else 2  # 三个词以上的组，只命中一个词多半是噪音
            scored = [x for x in scored if -x[0] >= need]
            for neg, _, u, sub, line_no, snip in scored[: args.max]:
                print(f"  正文 {-neg}/{len(terms)} {tag(k, u, sub)} L{line_no}｜{short(snip, args.width)}")
                shown += 1
        if shown == 0:
            print("  无命中")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def common_args(p):
        p.add_argument("--kind", required=True, choices=SPECS)
        p.add_argument("--file", help="不读正式母版时指定稿件路径")
        p.add_argument("--run", help="运行目录：按开轮时记录的母版快照定位（提取时必须给）")

    p = sp.add_parser("verify"); common_args(p)
    p = sp.add_parser("list"); common_args(p); p.add_argument("--range", help="如 1-50")
    p = sp.add_parser("find"); common_args(p); p.add_argument("keywords", nargs="+"); p.add_argument("--max", type=int, default=20)
    p = sp.add_parser("grep"); common_args(p); p.add_argument("pattern"); p.add_argument("--max", type=int, default=15); p.add_argument("--width", type=int, default=80)
    p = sp.add_parser("get"); common_args(p); p.add_argument("--id", type=int, required=True)
    p.add_argument("--sub", type=int); p.add_argument("--label", choices=LABELS); p.add_argument("--max-chars", type=int, default=6000)
    p = sp.add_parser("probe"); p.add_argument("--run"); p.add_argument("--kind", default="all", choices=["all", *SPECS])
    p.add_argument("groups", nargs="+", help="每个案例一组：& 连接应同时出现的词，| 写同义，如 '甜品&加盟&四十万|40 万'")
    p.add_argument("--max", type=int, default=4, help="每组每个库最多几行"); p.add_argument("--width", type=int, default=60)
    p = sp.add_parser("getmany"); p.add_argument("--run"); p.add_argument("items", nargs="+", help="t1:4 i1:逻辑 m1")
    p.add_argument("--max-chars", type=int, default=2500, help="每个位置最多输出几字")
    args = ap.parse_args()
    return {"verify": cmd_verify, "list": cmd_list, "find": cmd_find, "grep": cmd_grep, "get": cmd_get,
            "probe": cmd_probe, "getmany": cmd_getmany}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
