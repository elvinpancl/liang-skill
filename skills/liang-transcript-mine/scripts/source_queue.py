#!/usr/bin/env python3
"""本轮来源队列。只输出编号、状态、大小、路径，从不输出正文。

用法：
  source_queue.py build  [--run DIR] [--stale-budget 10] [--stale-short-budget 40]
                                                          调 check_source_increment.py 列队，做同场去重、沿用候选
  source_queue.py next   [--run DIR] [--n 5]               取下一批子代理任务：长稿一篇一个，短稿合批
  source_queue.py status [--run DIR]                       已读完 / 已出候选 / 剩余 / 沿用 / 同场重复
  source_queue.py prompt [--run DIR] --id Q003[,Q004…]     输出填好变量的子代理提取指令（子代理自己调用）

队列写在 <运行目录>/来源队列.json。重复 build 时同一路径保留原编号。
new、changed、抖音新作全部入队；stale（旧标准处理过、需按新标准重读）按长稿 --stale-budget、短稿
--stale-short-budget 分别限量，其余记为「顺延」，在报告里如实写出剩余数。

三处省 token 的安排：
  短稿合批  SHORT_CHARS 字以内的来源一块就能读完，几篇合给一个子代理，用 read_source.py --pack 一次读几篇。
            短稿一篇开一个时，重复初始化上下文可能大于正文开销。
  同场去重  使用去标点后的 6 字片段重合度。阈值是待本地校准的启发式值，
            达到 DUP_RATIO 的保留较长一份，另一份记 duplicate_of，
            不派提取，发布后随主稿一起提交。
  沿用候选  已按现行标准读完、写过候选、文件没变但还没提交的来源（候选周的成果、因待补没提交的旧来源），
            直接拷入阅读记录和候选，不再重读。发布周由主线程裁定后随本轮提交。
"""
import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path
from common import (CHECK_SOURCE, CONFIG, ROOT, RUN_STATE_NAME, SCRATCH, STATE_DIR, dump_json, fmt_size, in_run, load_json, rel,
                    required_extractor, resolve_run)
from read_source import source_text

ORDER = {"抖音新作": 0, "new": 1, "changed": 2, "stale": 3}
SHORT_CHARS = 9000           # read_source 一块约 1 万字，9000 字以内一块读完
BATCH_N, BATCH_CHARS = 15, 40000
DUP_RATIO = 0.25
DUP_WINDOW_DAYS = 10         # 跨轮比较只看修改时间相近的已提交转写
CARRY_SINCE = str(CONFIG.get("carry_since", "0000-00-00"))  # 可配置兼容格式的起始日期
BASELINE = STATE_DIR / "processed_source_hashes.tsv"


def abspath(r):
    p = Path(r)
    return p if p.is_absolute() else (ROOT / r).resolve()


def sha_of(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def read_state(run, qid):
    rec = load_json(run / "阅读记录" / f"{qid}.json", {})
    cand = run / "候选" / f"{qid}.jsonl"
    return bool(rec.get("complete")), cand.exists()


def grams(text):
    """只比「# 原文」之后的原始转写（AI 智能总结每次生成都不同），去标点数字后取 6 字片段。"""
    i = text.find("# 原文")
    body = re.sub(r"[\W\d_]+", "", text[i:] if i >= 0 else text)
    return {body[k:k + 6] for k in range(0, max(0, len(body) - 6), 2)}


def overlap(a, b):
    return len(a & b) / max(1, min(len(a), len(b)))


def committed_transcripts():
    """基线里已提交的录音转写，供跨轮比较。"""
    out = []
    if not BASELINE.exists():
        return out
    with BASELINE.open(encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
        for line in f:
            r = dict(zip(head, line.rstrip("\n").split("\t"))).get("relative_path", "")
            if r.startswith("录音逐字稿/") and abspath(r).exists():
                out.append(r)
    return out


def mark_duplicates(run, items):
    """队列内长稿两两比较，再和修改时间相近的已提交转写比较。返回 [(编号, 对方, 重合度, 是否跳过)]。"""
    cache = {}

    def g(item=None, path=None):
        key = item["path"] if item else path
        if key not in cache:
            text = source_text(run, item)[1] if item else abspath(path).read_text(encoding="utf-8", errors="replace")
            cache[key] = grams(text)
        return cache[key]

    longs = [i for i in items if not i["deferred"] and not i["short"]]
    found = []
    for x in range(len(longs)):
        for y in range(x + 1, len(longs)):
            a, b = longs[x], longs[y]
            if a.get("duplicate_of") or b.get("duplicate_of"):
                continue
            r = overlap(g(a), g(b))
            if r >= DUP_RATIO:
                keep, drop = (a, b) if a["chars"] >= b["chars"] else (b, a)
                drop.update(deferred=True, duplicate_of=keep["id"], overlap=round(r, 3))
                found.append((drop["id"], keep["id"], r, True))
    queued = {i["path"] for i in items}
    done = [r for r in committed_transcripts() if r not in queued]
    for i in longs:
        if i.get("duplicate_of") or not i["path"].startswith("录音逐字稿/"):
            continue
        t0 = abspath(i["path"]).stat().st_mtime
        for r in done:
            if abs(abspath(r).stat().st_mtime - t0) > DUP_WINDOW_DAYS * 86400:
                continue
            ratio = overlap(g(i), g(path=r))
            if ratio < DUP_RATIO:
                continue
            if i["chars"] > 1.3 * len(abspath(r).read_text(encoding="utf-8", errors="replace")):
                i["possible_duplicate_of"] = r  # 新的一份明显更全，照常提取，合并时注意已写过的部分
                found.append((i["id"], r, ratio, False))
            else:
                i.update(deferred=True, duplicate_of=r, overlap=round(ratio, 3))
                found.append((i["id"], r, ratio, True))
            break
    return found


def carry_candidates(run, items, req):
    """已按现行标准读完、写过候选、还没提交的来源直接沿用，不再派提取：候选周的成果，以及因待补没提交的旧来源。
    先按路径找，路径变了（如抖音原文补归档到语料库）再按文件哈希找；最近一轮优先。"""
    by_path, by_sha = {}, {}
    for d in sorted(SCRATCH.glob("增量挖掘_*/运行_*")):  # 按时间排，后面的覆盖前面的
        if d.resolve() == run.resolve() or d.parent.name.split("_", 1)[1][:10] < CARRY_SINCE:
            continue
        q = load_json(in_run(d, "来源队列.json"), {"items": []})
        if q.get("extractor_version") != req:
            continue
        for i in q["items"]:
            rec = load_json(in_run(d, "阅读记录") / f"{i['id']}.json", {})
            cand = in_run(d, "候选") / f"{i['id']}.jsonl"
            if rec.get("complete") and rec.get("sha256") and cand.exists():
                hit = (d, i["id"], rec, cand)
                by_path[i["path"]] = hit
                by_sha[rec["sha256"]] = hit
    n = 0
    for item in items:
        p = abspath(item["path"])
        if item["deferred"] or not p.exists() or (run / "候选" / f"{item['id']}.jsonl").exists():
            continue
        sha = sha_of(p)
        hit = by_path.get(item["path"])
        if not hit or hit[2].get("sha256") != sha:
            hit = by_sha.get(sha)
        if not hit:
            continue
        d, old, rec, cand = hit
        origin = rec.get("carried_from") or f"{rel(d)}/{old}"  # 沿用件再沿用时记最初提取的那一轮，母版漂移按它比
        rows = []
        for ln in cand.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                c = json.loads(ln)
                c["id"] = re.sub(rf"^{re.escape(old)}-", f"{item['id']}-", str(c.get("id", "")))
                c["carried_from"] = c.get("carried_from") or origin
                rows.append(json.dumps(c, ensure_ascii=False))
        (run / "候选" / f"{item['id']}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        dump_json(run / "阅读记录" / f"{item['id']}.json", dict(rec, id=item["id"], path=item["path"], carried_from=origin))
        item["carried_from"] = origin
        n += 1
    return n


def dispatch_units(todo):
    """长稿一篇一个子代理；短稿按 BATCH_N 篇、BATCH_CHARS 字合批。"""
    units, batch, size = [], [], 0
    for i in todo:
        if not i.get("short"):
            units.append([i])
            continue
        if batch and (len(batch) >= BATCH_N or size + i.get("chars", 0) > BATCH_CHARS):
            units.append(batch)
            batch, size = [], 0
        batch.append(i)
        size += i.get("chars", 0)
    if batch:
        units.append(batch)
    return units


def cmd_build(args):
    run = resolve_run(args.run)
    req = required_extractor()
    res = subprocess.run([sys.executable, str(CHECK_SOURCE), "--require", req],
                         capture_output=True, text=True, cwd=str(CHECK_SOURCE.parent))
    if res.returncode != 0:
        print(res.stderr[-800:])
        return 1
    raw = json.loads(res.stdout)
    dump_json(run / "来源检查原始输出.json", raw)

    rows = []
    for status in ("new", "changed", "stale"):
        # 账号目录中的新增抖音原文单独标出，优先处理
        rows += [("抖音新作" if status == "new" and "/抖音研究/" in r else status, r) for r in raw[status]]
    rows += [("抖音新作", rel(p)) for p in sorted((run / "抖音原文").glob("*_原文版.md"))]  # 旧版落在运行目录的原文
    rows.sort(key=lambda x: (ORDER[x[0]], x[1]))

    old = {q["path"]: q["id"] for q in load_json(run / "来源队列.json", {}).get("items", [])}
    used = set(old.values())
    seq = max([int(i[1:]) for i in used] or [0])
    items, taken = [], {True: 0, False: 0}
    for status, r in rows:
        p = abspath(r)
        qid = old.get(r)
        if not qid:
            seq += 1
            qid = f"Q{seq:03d}"
        item = dict(id=qid, status=status, path=r, bytes=p.stat().st_size if p.exists() else None)
        item["chars"] = len(source_text(run, item)[1]) if p.exists() else 0
        item["short"] = item["chars"] <= SHORT_CHARS
        deferred = False
        if status == "stale":
            budget = args.stale_short_budget if item["short"] else args.stale_budget
            deferred = taken[item["short"]] >= budget
            taken[item["short"]] += 0 if deferred else 1
        item["deferred"] = deferred
        items.append(item)

    dups = mark_duplicates(run, items)
    carried = carry_candidates(run, items, req)
    dump_json(run / "来源队列.json", {"extractor_version": req, "stale_budget": args.stale_budget,
                                     "stale_short_budget": args.stale_short_budget, "items": items})

    active = [i for i in items if not i["deferred"]]
    todo = [i for i in active if not all(read_state(run, i["id"]))]
    by = {}
    for i in items:
        k = i["status"] + ("·同场重复" if i.get("duplicate_of") else "·顺延" if i["deferred"] else "")
        by[k] = by.get(k, 0) + 1
    print(f"提取标准 {req}｜检查到 {len(items)} 份｜本轮处理 {len(active)} 份，共 {fmt_size(sum(i['bytes'] or 0 for i in active))}"
          f"（长稿 {sum(not i['short'] for i in active)}，短稿 {sum(i['short'] for i in active)}）"
          f"｜待派 {len(dispatch_units(todo))} 个子代理任务")
    print("分布：" + "，".join(f"{k} {v}" for k, v in by.items()))
    for a, b, r, skipped in dups[:8]:
        tail = "不派提取，发布后随主稿提交" if skipped else "新稿明显更全，照常提取，合并时避开已写过的部分"
        print(f"同场转写：{a} 与 {b} 正文重合 {r:.2f}，{a} {tail}")
    if carried:
        print(f"沿用已读完的来源：{carried} 份（候选周成果或历史待补，文件未变），不再派提取；发布周由主线程裁定")
    if raw.get("missing_from_disk"):
        print(f"登记过但磁盘上找不到：{len(raw['missing_from_disk'])} 份（见 来源检查原始输出.json）")
    print(f"队列：{rel(run / '来源队列.json')}")
    return 0


def pending(run):
    q = load_json(run / "来源队列.json")
    if not q:
        print("还没有队列，先跑 source_queue.py build")
        sys.exit(1)
    out = []
    for i in q["items"]:
        if i["deferred"]:
            continue
        done, cand = read_state(run, i["id"])
        if not (done and cand):
            out.append((i, done, cand))
    return q, out


def cmd_next(args):
    run = resolve_run(args.run)
    q, todo = pending(run)
    flags = {i["id"]: done for i, done, _ in todo}
    units = dispatch_units([i for i, _, _ in todo])
    for u in units[: args.n]:
        if len(u) == 1 and not u[0].get("short"):
            i = u[0]
            print(f"{i['id']}\t{i['status']}\t{fmt_size(i['bytes'] or 0)}\t"
                  f"{'已读完待出候选' if flags[i['id']] else '未读完'}\t{i['path']}")
        else:
            ids = ",".join(i["id"] for i in u)
            print(f"{ids}\t短稿合批 {len(u)} 篇\t{sum(i.get('chars', 0) for i in u)} 字\t一个子代理：prompt --id {ids}")
    if not units:
        print("本轮队列已全部读完并出候选")
    elif len(units) > args.n:
        print(f"…其余 {len(units) - args.n} 个子代理任务")


def cmd_status(args):
    run = resolve_run(args.run)
    q, todo = pending(run)
    active = [i for i in q["items"] if not i["deferred"]]
    dups = [i for i in q["items"] if i.get("duplicate_of")]
    deferred = len(q["items"]) - len(active) - len(dups)
    states = [read_state(run, i["id"]) for i in active]
    carried = sum(1 for i in active if i.get("carried_from"))
    print(f"本轮 {len(active)} 份：读完 {sum(d for d, _ in states)}，出候选 {sum(c for _, c in states)}，"
          f"未完成 {len(todo)}（{len(dispatch_units([i for i, _, _ in todo]))} 个子代理任务）；"
          f"其中沿用 {carried} 份；同场重复不提取 {len(dups)} 份；顺延到下轮 {deferred} 份")
    for i, done, cand in todo[:10]:
        print(f"  未完成 {i['id']} {'读完未出候选' if done else '未读完'} {i['path']}")
    for i in dups[:5]:
        print(f"  同场重复 {i['id']} → {i['duplicate_of']}（重合 {i.get('overlap')}）{i['path']}")


SKILL_DIR = Path(__file__).resolve().parent.parent


def cmd_prompt(args):
    """主线程只给子代理发一行「先运行这条命令」，完整指令由子代理自己取，不进主线程上下文。"""
    run = resolve_run(args.run)
    by_id = {i["id"]: i for i in load_json(run / "来源队列.json", {"items": []})["items"]}
    ids = [x.strip() for x in args.id.split(",") if x.strip()]
    missing = [x for x in ids if x not in by_id]
    if not ids or missing:
        print(f"队列里没有 {'、'.join(missing) or '这些编号'}")
        return 1
    shorts = [x for x in ids if by_id[x].get("short")]
    longs = [x for x in ids if x not in shorts]
    text = (SKILL_DIR / "references" / "extractor_prompt_脱敏版.md").read_text(encoding="utf-8")
    body = text.split("\n---\n", 1)[1]
    fill = {"{RUN}": str(run), "{QIDS}": " ".join(ids), "{QIDS_COMMA}": ",".join(ids),
            "{SHORTS}": ",".join(shorts) or "无", "{LONGS}": " ".join(longs) or "无",
            "{QID}": ids[0], "{SCRIPTS}": str(SKILL_DIR / "scripts")}
    for k, v in fill.items():
        body = body.replace(k, v)
    print(body.strip())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("build"); p.add_argument("--run")
    p.add_argument("--stale-budget", type=int, default=10, help="旧标准长稿每轮读几份")
    p.add_argument("--stale-short-budget", type=int, default=40, help="旧标准短稿每轮读几份（合批读）")
    p = sp.add_parser("next"); p.add_argument("--run"); p.add_argument("--n", type=int, default=5)
    p = sp.add_parser("status"); p.add_argument("--run")
    p = sp.add_parser("prompt"); p.add_argument("--run"); p.add_argument("--id", required=True, help="一个或逗号分隔的几个编号")
    args = ap.parse_args()
    return {"build": cmd_build, "next": cmd_next, "status": cmd_status, "prompt": cmd_prompt}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
