#!/usr/bin/env python3
"""把 staging 里生成好的草稿装进剪映 Mac 版草稿库。

用法：
  python jy_install.py --staging <staging/草稿名> [--name 草稿名] [--draft-root DIR] [--root-meta FILE] [--check]

- 草稿库路径：--draft-root，或环境变量 JIANYING_DRAFT_ROOT，缺省为剪映默认位置。
  草稿库可以放在外置盘；注册表 root_meta_info.json 仍在本机用户目录（--root-meta 或 JIANYING_ROOT_META）。
- 同名草稿已存在就拒绝，不覆盖、不删除任何已有草稿；每次装新版本用新名字。
- 剪映在运行时拒绝（进程名 VideoFusion-macOS 或 JianyingPro）。
- 注册表安装前自动备份到同目录 root_meta_info.json.<时间>.bak。
- --check 只做安装前检查，不动任何文件。

依赖 vendor/mac_draft.py（video-shotcraft，Apache-2.0，未改动）补齐 Mac 版差异：
入口文件 draft_info.json、platform 设备指纹、媒体打包进 Resources/ 并登记。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import jy_common

HERE = Path(__file__).resolve().parent


def _load_mac_draft(root: Path, meta: Path):
    spec = importlib.util.spec_from_file_location("mac_draft", HERE / "vendor" / "mac_draft.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DRAFT_ROOT = str(root)
    module.ROOT_META = str(meta)
    module.jianying_running = jy_common.jianying_running
    return module


def preflight(staging: Path, name: str, root: Path, meta: Path) -> list[str]:
    problems = []
    if not (staging / "draft_content.json").is_file():
        problems.append(f"staging 里没有 draft_content.json：{staging}")
    if not root.is_dir():
        problems.append(f"草稿库不存在，外置盘可能没挂载：{root}")
    elif (root / name).exists():
        problems.append(f"草稿名已存在，请换一个名字：{name}")
    if not meta.is_file():
        problems.append(f"找不到剪映注册表：{meta}")
    if jy_common.jianying_running():
        problems.append("剪映正在运行，请先完全退出（Cmd+Q）")
    manifest = staging / "build_manifest.json"
    if manifest.is_file() and json.loads(manifest.read_text(encoding="utf-8")).get("surrogate"):
        problems.append("这份草稿用的是替身素材，只能自测，不能安装")
    return problems


def install_new(staging: Path, name: str, root: Path, meta: Path) -> dict:
    problems = preflight(staging, name, root, meta)
    if problems:
        raise RuntimeError("；".join(problems))
    mac_draft = _load_mac_draft(root, meta)
    info = mac_draft.macify(str(staging), name)
    backup = mac_draft.install(str(staging), name, info)
    installed = root / name
    media = list((installed / "Resources").glob("*"))
    return {"draft_dir": str(installed), "registry_backup": backup, "media_files": len(media),
            "draft_info_exists": (installed / "draft_info.json").is_file()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--staging", required=True, type=Path)
    parser.add_argument("--name", help="缺省用 staging 目录名")
    parser.add_argument("--draft-root")
    parser.add_argument("--root-meta")
    parser.add_argument("--check", action="store_true", help="只检查，不安装")
    args = parser.parse_args()
    staging = args.staging.resolve()
    name = args.name or staging.name
    if staging.name != name:
        parser.error("staging 目录名要和草稿名一致：文字字体等路径是按最终草稿名写进去的")
    root, meta = jy_common.draft_root(args.draft_root), jy_common.root_meta(args.root_meta)
    if args.check:
        problems = preflight(staging, name, root, meta)
        print("可以安装" if not problems else "不能安装：\n- " + "\n- ".join(problems))
        raise SystemExit(1 if problems else 0)
    result = install_new(staging, name, root, meta)
    print(f"已安装并回读：{result['draft_dir']}\n素材文件：{result['media_files']} 项\n"
          f"注册表备份：{result['registry_backup']}")


if __name__ == "__main__":
    main()
