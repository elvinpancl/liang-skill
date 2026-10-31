#!/usr/bin/env python3
"""Static checks for the liang-hook protocol and structure library."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "SKILL.md"
STRUCTURES = ROOT / "structures_脱敏版.md"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_all(text: str, needles: list[str], label: str) -> None:
    missing = [item for item in needles if item not in text]
    if missing:
        fail(f"{label} missing: {', '.join(missing)}")


def structure_blocks(text: str) -> list[tuple[int, str]]:
    matches = list(re.finditer(r"^\*\*#(\d+)「", text, re.MULTILINE))
    blocks: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((int(match.group(1)), text[match.start() : end]))
    return blocks


def main() -> None:
    if not SKILL.is_file() or not STRUCTURES.is_file():
        fail("SKILL.md or structures_脱敏版.md not found")

    skill = SKILL.read_text(encoding="utf-8")
    structures = STRUCTURES.read_text(encoding="utf-8")

    require_all(
        skill,
        [
            "## 证据边界与方法内核",
            "## 第一步 收稿与守门",
            "## 第二步 存量开头诊断",
            "## 第三步 锁定角度",
            "## 第四步 库匹配生成",
            "## 第五步 验收与指路",
            "## Refusals",
        ],
        "required sections",
    )
    require_all(
        skill,
        [
            "把正文给我，先看有没有值得被放大的东西。",
            "开头只治最致命的那一处，别拿六维凑数。",
            "先定你要把观众往哪儿拽，方向不定，不写。",
            "只换内容词，不动钩子骨架。",
            "能兑现正文、能进入预测卡，这个开头才算完成。",
        ],
        "nail lines",
    )
    require_all(
        skill,
        [
            "from: liang-hook",
            "draft:",
            "platform:",
            "structure_id:",
            "selected_version:",
            "evidence_level:",
            "next: liang-predict",
        ],
        "handoff fields",
    )
    require_all(skill, ["最近 90 天", "不少于 30 张", "完整复盘卡池"], "anchor policy")

    blocks = structure_blocks(structures)
    if not blocks:
        fail("no structure entries found")
    ids = [item[0] for item in blocks]
    if len(ids) != len(set(ids)):
        fail("structure IDs are not unique")
    if ids != sorted(ids):
        fail("structure IDs are not strictly increasing")

    seed_marker = structures.find("## 种子区")
    verified_marker = structures.find("## 自有验证区")
    if seed_marker < 0 or verified_marker < 0 or seed_marker >= verified_marker:
        fail("evidence sections missing or out of order")

    seed_text = structures[seed_marker:verified_marker]
    verified_text = structures[verified_marker:]
    if "统一为 `[待验证]`" not in seed_text:
        fail("seed evidence label missing")
    if "公开版未附带个人验证集" not in verified_text or "不能" not in verified_text:
        fail("verified selection-bias warning missing")

    verified_blocks = structure_blocks(verified_text)
    if verified_blocks:
        fail("public distribution must not include private verified entries")
    for entry_id, block in verified_blocks:
        require_all(
            block,
            ["实绩：", "证据：[结果已验证]", "来源状态："],
            f"verified entry #{entry_id}",
        )

    print(
        "ok: liang-hook static validation "
        f"({len(ids)} structures, {len(verified_blocks)} outcome-verified entries)"
    )


if __name__ == "__main__":
    main()
