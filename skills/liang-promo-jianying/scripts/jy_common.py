"""共用工具：帧与微秒换算、JSON 读写、ffmpeg 定位、整段解码计帧、系统字体查找。

帧区间一律左闭右开 [start, end)。微秒边界逐个取整：区间时长写作
f2us(end) - f2us(start)，不能单独取整时长，否则长片会累积 1 µs 级误差。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

DEFAULT_DRAFT_ROOT = Path.home() / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft"
JIANYING_PROCESSES = ("VideoFusion-macOS", "JianyingPro")


def f2us(frame: int | float, fps: int) -> int:
    return round(frame * 1_000_000 / fps)


def us2f(us: int, fps: int) -> int:
    return round(us * fps / 1_000_000)


def load_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: str | Path, data) -> None:
    """先写 .pending 再替换，写一半失败不会留下损坏的清单。"""
    path = Path(path)
    pending = path.with_name(path.name + ".pending")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffmpeg_bin() -> str:
    binary = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("找不到 ffmpeg；装好后放进 PATH，或用 FFMPEG_BIN 指定")
    return binary


def ffprobe_bin() -> str | None:
    return os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe")


def run(argv: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"命令失败（{proc.returncode}）：{' '.join(map(str, argv))}\n{proc.stderr[-4000:]}")
    return proc


def probe_video(path: str | Path) -> dict:
    """完整解码计帧，不信容器里申报的时长。有 ffprobe 用它，没有就用 ffmpeg 解码到 null。"""
    path = str(path)
    probe = ffprobe_bin()
    if probe:
        out = run([probe, "-v", "error", "-count_frames", "-show_streams", "-of", "json", path]).stdout
        streams = json.loads(out)["streams"]
        video = next(s for s in streams if s["codec_type"] == "video")
        return {"frames": int(video["nb_read_frames"]), "width": video["width"], "height": video["height"],
                "fps": float(Fraction(video["avg_frame_rate"])),
                "audio_streams": sum(s["codec_type"] == "audio" for s in streams)}
    proc = run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", path, "-map", "0:v:0", "-an",
                "-progress", "pipe:1", "-nostats", "-f", "null", "-"])
    stream = next((line for line in proc.stderr.splitlines() if "Video:" in line), "")
    size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", stream)
    fps = re.search(r"([0-9.]+) fps", stream)
    counts = re.findall(r"^frame=(\d+)\s*$", proc.stdout, flags=re.M)
    if not size or not fps or not counts:
        raise RuntimeError(f"读不出视频信息：{path}")
    head = proc.stderr.split("Stream mapping:", 1)[0]
    return {"frames": int(counts[-1]), "width": int(size[1]), "height": int(size[2]),
            "fps": float(fps[1]), "audio_streams": len(re.findall(r"Stream #0:.*Audio:", head))}


def image_size(path: str | Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def find_system_font(file_name: str) -> Path | None:
    """macOS 的可下载字体装在 AssetsV2 的哈希目录里，路径因机器而异，按文件名找最大的那份。

    FontServices 里同名的 Subsets 文件只是字形子集，不能用。
    """
    roots = [Path("/System/Library/AssetsV2"), Path("/Library/Fonts"), Path.home() / "Library/Fonts",
             Path("/System/Library/Fonts")]
    found: list[Path] = []
    for root in roots:
        if root.is_dir():
            found += [p for p in root.rglob(file_name) if p.is_file() and "Subsets" not in p.parts]
    return max(found, key=lambda p: p.stat().st_size) if found else None


def resolve(base: Path, value: str | None) -> Path | None:
    """计划文件里的相对路径相对于计划文件所在目录。"""
    if value is None:
        return None
    path = Path(os.path.expanduser(value))
    return path if path.is_absolute() else (base / path).resolve()


def draft_root(cli_value: str | None = None) -> Path:
    value = cli_value or os.environ.get("JIANYING_DRAFT_ROOT")
    return Path(os.path.expanduser(value)) if value else DEFAULT_DRAFT_ROOT


def root_meta(cli_value: str | None = None) -> Path:
    """注册表固定在本机用户目录；草稿库可以在外置盘，注册表不跟着走。"""
    value = cli_value or os.environ.get("JIANYING_ROOT_META")
    return Path(os.path.expanduser(value)) if value else DEFAULT_DRAFT_ROOT / "root_meta_info.json"


def jianying_running() -> bool:
    pattern = "|".join(JIANYING_PROCESSES)
    out = subprocess.run(["pgrep", "-fl", "-i", pattern], capture_output=True, text=True).stdout
    return bool(out.strip())
