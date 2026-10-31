#!/usr/bin/env python3
"""统计挖掘任务实际花了多少 token，用来对比改造前后。

用法：
  token_report.py --since 2026-10-05                 Codex 与 Claude Code 两边都统计
  token_report.py --since 2026-10-05 --host codex
  token_report.py --thread <会话编号前缀>                  只看某个会话（id 前缀即可）
  --cwd 过滤工作目录（默认读取 LIANG_KB_ROOT）；--gap 6 表示同一长线程里相隔 6 小时以上算两轮运行
  --detail 逐个列出子代理，看有没有分叉继承长上下文（起步上下文很大就是分叉）

Codex：读 ~/.codex/sessions 的 token_count 事件；子代理会话按 parent_thread_id 和时间段归到主运行。
Claude Code：读 ~/.claude/projects 下的会话与 subagents，按 message.id 去重累计 usage。
「上下文」指单次调用送进模型的输入 token，总量 ≈ 调用次数 × 上下文。
"""
import argparse, json, os, statistics, sys
from datetime import datetime, timedelta
from pathlib import Path

CODEX = Path.home() / ".codex" / "sessions"
CLAUDE = Path.home() / ".claude" / "projects"


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def codex_sessions(since, cwd_filter, thread):
    out = []
    for f in CODEX.rglob("rollout-*.jsonl"):
        if since and datetime.fromtimestamp(f.stat().st_mtime).date() < since.date():
            continue
        with f.open(encoding="utf-8", errors="ignore") as fh:
            try:
                meta = json.loads(fh.readline()).get("payload", {})
            except json.JSONDecodeError:
                continue
            sid = meta.get("id", "")
            if thread and not sid.startswith(thread) and not str(meta.get("parent_thread_id", "")).startswith(thread):
                continue
            if cwd_filter and cwd_filter not in meta.get("cwd", ""):
                continue
            events, prev_tot, prev_cache = [], 0, 0
            for line in fh:
                if '"token_count"' not in line:
                    continue
                o = json.loads(line)
                info = (o.get("payload") or {}).get("info")
                if not info:
                    continue
                tot, last = info["total_token_usage"], info.get("last_token_usage", {})
                if not events:
                    # 续接或分叉的会话，累计值里带着之前的用量；首个事件只算本次调用
                    prev_tot = tot["total_tokens"] - last.get("total_tokens", 0)
                    prev_cache = tot.get("cached_input_tokens", 0) - last.get("cached_input_tokens", 0)
                events.append(dict(t=ts(o["timestamp"]), total=tot["total_tokens"] - prev_tot,
                                   cached=tot.get("cached_input_tokens", 0) - prev_cache,
                                   ctx=last.get("input_tokens", 0)))
                prev_tot, prev_cache = tot["total_tokens"], tot.get("cached_input_tokens", 0)
        if events:
            out.append(dict(host="codex", id=sid, parent=meta.get("parent_thread_id"),
                            name=meta.get("agent_nickname") or "", events=events))
    return out


def claude_sessions(since, cwd_filter, thread):
    out = []
    for f in CLAUDE.rglob("*.jsonl"):
        if since and datetime.fromtimestamp(f.stat().st_mtime).date() < since.date():
            continue
        is_sub = f.parent.name == "subagents"
        sid = f.parent.parent.name if is_sub else f.stem
        if thread and not sid.startswith(thread):
            continue
        seen, events, cwd_ok = set(), [], not cwd_filter
        with f.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if not cwd_ok and cwd_filter in line[:2000] and '"cwd"' in line[:2000]:
                    cwd_ok = True
                if '"usage"' not in line:
                    continue
                o = json.loads(line)
                msg = o.get("message") or {}
                u, mid = msg.get("usage"), msg.get("id")
                if not u or mid in seen:
                    continue
                seen.add(mid)
                ctx = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                events.append(dict(t=ts(o["timestamp"]), total=ctx + u.get("output_tokens", 0),
                                   cached=u.get("cache_read_input_tokens", 0), ctx=ctx))
        if events and cwd_ok:
            out.append(dict(host="claude", id=f.stem if is_sub else sid, parent=sid if is_sub else None,
                            name="subagent" if is_sub else "", events=events))
    return out


def split_runs(events, gap):
    runs, cur = [], []
    for e in sorted(events, key=lambda x: x["t"]):
        if cur and e["t"] - cur[-1]["t"] > gap:
            runs.append(cur); cur = []
        cur.append(e)
    if cur:
        runs.append(cur)
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since"); ap.add_argument("--thread"); ap.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    ap.add_argument("--cwd", default=os.environ.get("LIANG_KB_ROOT")); ap.add_argument("--gap", type=float, default=6)
    ap.add_argument("--detail", action="store_true", help="逐个列出子代理：调用数、总量、起步与最大上下文")
    args = ap.parse_args()
    if not args.cwd and not args.thread:
        ap.error("请设置 LIANG_KB_ROOT、--cwd 或 --thread，避免扫描无关项目会话。")
    since = datetime.fromisoformat(args.since) if args.since else None
    if not (since or args.thread):
        print("给 --since 或 --thread")
        return 1
    gap = timedelta(hours=args.gap)
    sessions = []
    if args.host in ("codex", "both"):
        sessions += codex_sessions(since, args.cwd, args.thread)
    if args.host in ("claude", "both"):
        sessions += claude_sessions(since, args.cwd, args.thread)

    by_id = {s["id"]: s for s in sessions}

    def root(s):
        # 子代理还能再开子代理，沿 parent 链找到最上层的主会话
        while s["parent"] in by_id and by_id[s["parent"]] is not s:
            s = by_id[s["parent"]]
        return s["parent"] or s["id"]

    mains = [s for s in sessions if not s["parent"]]
    subs = [s for s in sessions if s["parent"]]
    for x in subs:
        x["root"] = root(x)
    rows = []
    for s in mains:
        for r in split_runs(s["events"], gap):
            if since and r[-1]["t"].date() < since.date():
                continue
            a, b = r[0]["t"], r[-1]["t"]
            sub_total = sum(e["total"] for x in subs if x["root"] == s["id"]
                            for e in x["events"] if a - timedelta(minutes=5) <= e["t"] <= b + timedelta(hours=1))
            total = sum(e["total"] for e in r)
            cached = sum(e["cached"] for e in r)
            rows.append((a, s["host"], s["id"][:8], len(r), total, cached / total if total else 0,
                         statistics.median(e["ctx"] for e in r), sub_total))
    # 主会话不在范围内、只剩子代理时也列出来
    main_ids = {s["id"] for s in mains}
    for x in subs:
        if x["root"] not in main_ids:
            r = x["events"]
            total = sum(e["total"] for e in r)
            rows.append((r[0]["t"], x["host"], f"子:{x['id'][:6]}", len(r), total,
                         sum(e["cached"] for e in r) / total if total else 0, statistics.median(e["ctx"] for e in r), 0))
    rows.sort()
    print("开始时间(UTC)      宿主    会话       调用数  主线程总量  缓存占比  上下文中位数  子代理总量")
    for a, host, sid, n, total, cr, med, sub in rows:
        print(f"{a:%Y-%m-%d %H:%M}  {host:<6}  {sid:<9}  {n:>6}  {total/1e4:>8.0f} 万  {cr:>6.0%}  {med/1e4:>9.1f} 万  {sub/1e4:>8.0f} 万")
    if not rows:
        print("（无匹配会话）")
    if args.detail and subs:
        print("\n子代理明细：开始时间(UTC)  所属主会话  名称  调用数  总量  起步上下文  最大上下文")
        for x in sorted(subs, key=lambda x: x["events"][0]["t"]):
            ev = x["events"]
            if since and ev[-1]["t"].date() < since.date():
                continue
            print(f"  {ev[0]['t']:%Y-%m-%d %H:%M}  {x['root'][:8]}  {(x['name'] or x['id'])[:14]:<14}  {len(ev):>4}"
                  f"  {sum(e['total'] for e in ev)/1e4:>7.0f} 万  {ev[0]['ctx']/1e4:>6.1f} 万  {max(e['ctx'] for e in ev)/1e4:>6.1f} 万")
    return 0


if __name__ == "__main__":
    sys.exit(main())
