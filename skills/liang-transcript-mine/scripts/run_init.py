#!/usr/bin/env python3
"""开一轮增量挖掘：建运行目录，汇总本轮需要知道的全部状态，只打印 30 行以内。

用法：
  python3 run_init.py                 # 新建 scratchpad/增量挖掘_YYYY-MM-DD/运行_HHMMSS/
  python3 run_init.py --status        # 只看状态，不建目录
  python3 run_init.py --mode 合并     # 用户明确要求本周就发布时，手动指定模式

取代过去每轮开头的几十次读取：SOURCE_OF_TRUTH、返工状态、契约路径、发布锁、提取器版本。

默认发布节奏是双周：每周都取来源、出候选、更新案例库；距上次发布不足 13 天的一轮只做到候选，
满 13 天的一轮沿用本周期候选周的候选，合并两周材料后发布。上次发布日期取正式母版文件名里的日期。
"""
import argparse, re, sys
from datetime import date, datetime
from common import (RUN_STATE_NAME, KIND_ZH, contracts, dump_json, fmt_size, formal_masters,
                    load_json, new_run_dir, probe_lock, rel, required_extractor,
                    rework_status_path, short, snapshot_masters)

PUBLISH_EVERY_DAYS = 13  # 周一跑，两周一发；留一天余量，避免顺延一天就错过发布周


def last_publish_date(masters):
    """正式母版文件名带发布日期，如 …_V14_2026-10-19_改写版.md；取三份里最晚的一个。"""
    days = []
    for p in masters.values():
        m = re.search(r"_(\d{4}-\d{2}-\d{2})_", p.name)
        if m:
            days.append(date.fromisoformat(m.group(1)))
    return max(days) if days else None


def decide_mode(rework, last, today, override=None):
    """返工未完成云端发布时只整理候选；否则按双周节奏决定本轮是否发布。"""
    if override:
        return override, f"手动指定本轮为{override}模式"
    if rework and rework.get("cloud_publication_complete") is False:
        return "候选", "全量返工尚未完成发布：本轮只取来源、读全文、按卡号模块整理候选，不改正式稿、不发布"
    if last is None:
        return "候选", "母版文件名里找不到发布日期，保持候选模式；合并由用户明确要求"
    gap = (today - last).days
    if gap < PUBLISH_EVERY_DAYS:
        return "候选", (f"双周发布的候选周：距上次发布（{last}）{gap} 天。本轮取来源、读全文、出候选、更新案例库；"
                       "不改正式稿、不发布、不提交来源状态")
    return "合并", (f"发布周：距上次发布（{last}）{gap} 天。列队时会沿用本周期候选周的候选，合并两周材料后发布；"
                   "飞书写入仍需已有授权与宿主审批")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--mode", choices=["候选", "合并"], help="只在用户明确要求时覆盖双周节奏")
    args = ap.parse_args()

    masters = formal_masters()
    rw_path = rework_status_path()
    rework = load_json(rw_path) if rw_path else None
    today = date.today()
    last = last_publish_date(masters)
    mode, mode_note = decide_mode(rework, last, today, args.mode)
    lock_free = probe_lock()
    cons = contracts()
    state = {
        "started_at": datetime.now().astimezone().isoformat(),
        "mode": mode,
        "mode_note": mode_note,
        "last_publish_date": str(last) if last else None,
        "days_since_publish": (today - last).days if last else None,
        "extractor_version": required_extractor(),
        "lock_free_at_start": lock_free,
        # 开轮快照：本轮所有定位都按这里的路径和哈希，母版中途换版也不受影响
        "masters": snapshot_masters(),
        "contracts": {k: str(p) if p else None for k, p in cons.items()},
        "rework_status": str(rw_path) if rw_path else None,
        "rework_stage": rework.get("stage") if rework else None,
        "rework_next_action": rework.get("next_automation_action") if rework else None,
        "rework_dir": rework.get("full_rewrite_directory") if rework else None,
    }

    if args.status:
        run = None
    else:
        run = new_run_dir()
        for sub in ("候选", "阅读记录"):  # 子代理直接写，不用先探路建目录
            (run / sub).mkdir()
        state["run_dir"] = str(run)
        dump_json(run / RUN_STATE_NAME, state)

    out = []
    out.append(f"运行目录：{rel(run) if run else '（--status，未建）'}")
    out.append(f"本轮模式：{mode}｜{mode_note}")
    out.append(f"发布锁：{'空闲' if lock_free else '被占用，其他写入者在跑；本轮不得写正式稿或飞书'}")
    out.append(f"提取器版本：{state['extractor_version']}")
    for k, p in masters.items():
        size = fmt_size(p.stat().st_size) if p.exists() else "不存在！"
        out.append(f"{KIND_ZH[k]}母版：{rel(p)}（{size}）")
    for k, p in cons.items():
        out.append(f"契约·{k}：{rel(p) if p else '未找到'}")
    if rework:
        out.append(f"返工状态：{rel(rw_path)}｜stage={rework.get('stage')}")
        if rework.get("next_automation_action"):
            out.append(f"返工给定时任务的指示（与本轮模式冲突时以本轮模式为准）：{short(rework['next_automation_action'], 400)}")
    out.append("母版只用 card_locator.py --run <运行目录> 按卡号/模块读取，不要整份打开；本轮按开轮快照定位。")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
