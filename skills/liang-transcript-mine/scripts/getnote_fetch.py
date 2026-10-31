#!/usr/bin/env python3
"""从用户显式配置的 Get 笔记订阅读取新作原文，不创建或删除远端笔记。

凭据只从 GETNOTE_API_KEY、GETNOTE_CLIENT_ID 环境变量读取，不记录或打印。
订阅主题与账号映射取知识库配置的 getnote。缺配置时退出，不访问网络。
list 读取订阅列表；fetch 读取 list 已发现作品的原文，原文与 AI 摘要分别存储。
"""
import argparse, hashlib, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from common import CONFIG, DOUYIN_LEDGER, die, KB, ROOT, SCRATCH, dump_json, load_json, rel, resolve_run, short

API = "https://openapi.biji.com/open/api/v1"
TOPIC = ""
ACCOUNTS = {}
ACCOUNT_DIRS = {}
AID = re.compile(r"(?<!\d)(7\d{18})(?!\d)")
RAW_DIRS = []


def configure():
    global TOPIC, ACCOUNTS, ACCOUNT_DIRS, RAW_DIRS
    settings = CONFIG.get("getnote")
    if not isinstance(settings, dict) or not settings.get("topic_id"):
        die("未配置 getnote.topic_id。只处理本地逐字稿时跳过 Get 笔记步骤。")
    accounts = settings.get("accounts")
    if not isinstance(accounts, dict) or not accounts:
        die("请在 getnote.accounts 配置订阅账号全名到本地短名的映射。")
    for name, alias in accounts.items():
        if not all(isinstance(x, str) and x and x not in (".", "..") and not any(c in x for c in ('/', '\\')) for x in (name, alias)):
            die("订阅名称和短名必须是非空目录名称，不能包含路径分隔符。")
    if len(set(accounts.values())) != len(accounts):
        die("getnote.accounts 的短名不能重复。")
    TOPIC, ACCOUNTS = str(settings["topic_id"]), accounts
    ACCOUNT_DIRS = {alias: name for name, alias in ACCOUNTS.items()}
    RAW_DIRS = [KB / "语料库" / name / "抖音研究" for name in accounts]


def raw_dir(account, day=None):
    """作品原文的归档目录：语料库/<账号>/抖音研究/<YYYY-MM-DD>/逐字稿/。"""
    day = day or datetime.now().astimezone().strftime("%Y-%m-%d")
    return KB / "语料库" / ACCOUNT_DIRS[account] / "抖音研究" / day / "逐字稿"


def headers():
    key = os.environ.get("GETNOTE_API_KEY")
    client = os.environ.get("GETNOTE_CLIENT_ID")
    if not key or not client:
        die("缺少 GETNOTE_API_KEY 或 GETNOTE_CLIENT_ID 环境变量；未发起网络请求。")
    return {"Authorization": "Bearer " + key, "X-Client-ID": client}


def get(h, path, params):
    req = urllib.request.Request(f"{API}{path}?{urllib.parse.urlencode(params)}", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"success": False, "http_status": e.code, "body": e.read().decode()[:500]}
    except Exception as e:  # 网络失败如实记录，不当成「无新增」
        return {"success": False, "error_type": type(e).__name__, "message": str(e)[:300]}


def known_ids():
    """返回 (已处理或已有原文的 ID, 只在历史清单里出现的 ID)。"""
    have_raw = set(AID.findall(DOUYIN_LEDGER.read_text(encoding="utf-8"))) if DOUYIN_LEDGER.exists() else set()
    roots = RAW_DIRS + sorted(SCRATCH.glob("增量挖掘_*"))
    for base in roots:
        for dp, _, files in os.walk(base):
            for fn in files:
                if "原文" in fn or "逐字稿" in dp:
                    have_raw.update(AID.findall(fn))
    listed = set()
    for acct in ACCOUNTS:
        for csv in (KB / "语料库" / acct / "抖音研究").glob("*/原始清单/*.csv"):
            listed.update(AID.findall(csv.read_text(encoding="utf-8", errors="ignore")))
    return have_raw, listed - have_raw


def cmd_list(args):
    run = resolve_run(args.run)
    out_dir = run / "抖音检查"
    h = headers()
    bl = get(h, "/resource/knowledge/bloggers", {"topic_id": TOPIC, "page": 1})
    if not bl.get("success", True) or "data" not in bl:
        dump_json(out_dir / "订阅账号_失败.json", bl)
        print(f"订阅账号列表获取失败：{short(json.dumps(bl, ensure_ascii=False), 120)}；记为未完成，不是无新增")
        return 1
    have_raw, listed_only = known_ids()
    items, failures = [], []
    for b in bl["data"].get("bloggers", []):
        acc = ACCOUNTS.get(b.get("account_name"))
        if not acc:
            continue
        fid = str(b.get("follow_id_str") or b.get("follow_id"))
        for page in range(1, args.pages + 1):
            time.sleep(3)
            resp = get(h, "/resource/knowledge/blogger/contents", {"topic_id": TOPIC, "follow_id": fid, "page": page})
            dump_json(out_dir / f"{acc}_订阅第{page}页.json", resp)
            if "data" not in resp:
                failures.append(f"{acc} 第{page}页")
                continue
            for r in resp["data"].get("contents", []):
                m = re.search(r"/(?:video|note|article)/(\d+)", r.get("post_url", ""))
                if m:
                    items.append(dict(account=acc, aweme_id=m.group(1), title=r.get("post_title", ""),
                                      publish=r.get("post_publish_time"), post_id_alias=r.get("post_id_alias"),
                                      post_url=r.get("post_url")))
    new = [i for i in items if i["aweme_id"] not in have_raw and i["aweme_id"] not in listed_only]
    no_raw = [i for i in items if i["aweme_id"] in listed_only]
    dump_json(out_dir / "订阅清单.json", {"checked_at": datetime.now(timezone.utc).isoformat(), "pages": args.pages,
                                          "items": items, "new": new, "listed_without_raw": no_raw,
                                          "failures": failures})
    print(f"订阅作品 {len(items)} 条｜新作 {len(new)}｜有历史清单无原文 {len(no_raw)}｜失败页 {len(failures)}")
    for i in new[:20]:
        print(f"  新 {i['account']} {i['aweme_id']} {short(i['title'], 30)}")
    for i in no_raw[:5]:
        print(f"  无原文 {i['account']} {i['aweme_id']} {short(i['title'], 30)}")
    if failures:
        print(f"  失败：{failures}（下轮重试，报告里写明）")
    print(f"明细：{rel(out_dir / '订阅清单.json')}")
    return 0


def cmd_fetch(args):
    run = resolve_run(args.run)
    lst = load_json(run / "抖音检查" / "订阅清单.json")
    if not lst:
        print("先跑 getnote_fetch.py list")
        return 1
    pool = {i["aweme_id"]: i for i in lst["items"]}
    targets = [pool[a] for a in args.ids if a in pool] if args.ids else lst["new"]
    missing = [a for a in (args.ids or []) if a not in pool]
    h = headers()
    log = []
    for r in targets:
        od = raw_dir(r["account"])
        time.sleep(3)
        d = get(h, "/resource/knowledge/blogger/content/detail", {"topic_id": TOPIC, "post_id": r["post_id_alias"]})
        dump_json(run / "抖音检查" / "详情" / f"{r['aweme_id']}.json", d)
        data = d.get("data") or {}
        z = dict(r, api_success=d.get("success"), fetched_at=datetime.now(timezone.utc).isoformat())
        for kind, body in (("原文", str(data.get("post_media_text") or "")), ("AI摘要", str(data.get("post_summary") or ""))):
            z[f"{kind}_chars"] = len(body)
            if body.strip():
                od.mkdir(parents=True, exist_ok=True)
                p = od / f"{r['account']}_{r['aweme_id']}_GetNote订阅_{kind}版.md"
                if not p.exists():
                    p.write_text(body, encoding="utf-8")
                z[f"{kind}_path"] = rel(p)
                z[f"{kind}_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        z["status"] = "原文已落盘" if z.get("原文_path") else "原文缺失，记待重试"
        log.append(z)
        print(f"  {r['account']} {r['aweme_id']} 原文 {z['原文_chars']} 字｜{z['status']}")
    dump_json(run / "抖音检查" / "获取记录.json", {"items": log, "unknown_ids": missing})
    ok = sum(1 for z in log if z.get("原文_path"))
    print(f"获取 {len(log)} 条：原文落盘 {ok}，缺失 {len(log) - ok}" + (f"；不在订阅清单里的 ID {missing}" if missing else ""))
    print("下一步：source_queue.py build 把新原文收进队列")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("list"); p.add_argument("--run"); p.add_argument("--pages", type=int, default=1)
    p = sp.add_parser("fetch"); p.add_argument("--run"); p.add_argument("--ids", nargs="*")
    args = ap.parse_args()
    configure()
    return {"list": cmd_list, "fetch": cmd_fetch}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
