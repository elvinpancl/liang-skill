"""liang-transcript-mine 各脚本共用的路径与小工具。

所有路径都从知识库实际文件解析，不把某一轮的日期路径写死：
正式母版读 SOURCE_OF_TRUTH.md，契约与返工状态取同类文件里日期最新的一份。
"""
import fcntl, glob, hashlib, json, os, re, sys
from datetime import datetime
from pathlib import Path

def die(msg, code=2):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


_root = os.environ.get("LIANG_KB_ROOT")
if not _root:
    die("未设置 LIANG_KB_ROOT。请按本 Skill 的 README.md 配置知识库；不会使用作者的本机目录。")
KB = Path(_root).expanduser().resolve()
if not KB.is_dir():
    die("LIANG_KB_ROOT 必须指向已存在的知识库目录。")
CONFIG_PATH = Path(os.environ.get("LIANG_TRANSCRIPT_CONFIG", str(KB / "liang-transcript.json"))).expanduser()
try:
    CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError):
    die("无法读取知识库配置。请复制 assets/config.example.json 为 liang-transcript.json 并填写真实路径。")
if not isinstance(CONFIG, dict):
    die("知识库配置顶层必须是 JSON 对象。")


def kb_path(value):
    """配置中的文件必须位于用户显式选定的知识库内。"""
    if not isinstance(value, str) or not value.strip():
        die("配置路径必须是非空字符串。")
    p = (KB / value).resolve()
    if not p.is_relative_to(KB):
        die("配置路径必须位于 LIANG_KB_ROOT 内。")
    return p


ROOT = kb_path(CONFIG.get("workspace_dir", "直播录音资料"))
SCRATCH = ROOT / "scratchpad"
STATE_DIR = SCRATCH / "定时更新"
SOT = kb_path(CONFIG.get("source_of_truth", "语料库/SOURCE_OF_TRUTH.md"))
LOCK = STATE_DIR / "knowledge_publish.lock"
CHECK_SOURCE = Path(__file__).with_name("check_source_increment.py")
DOUYIN_LEDGER = STATE_DIR / "douyin_processed_aweme_ids.tsv"
PENDING = STATE_DIR / "pending_source_review.json"
RUN_STATE_NAME = "运行状态.json"

# SOURCE_OF_TRUTH 快速查找表里的行名 → kind
SOT_ROWS = {
    "tactics": "打法当前正式版本",
    "insights": "洞见当前正式版本",
    "method": "营销策划诊断与推导方法（独立文档）",
}
KIND_ZH = {"tactics": "打法", "insights": "洞见", "method": "方法"}


def latest(pattern):
    """按文件名排序取最新一份（文件名里带日期），没有返回 None。"""
    hits = sorted(glob.glob(str(pattern)))
    return Path(hits[-1]) if hits else None


def contracts():
    result = {}
    configured = CONFIG.get("contracts", {})
    for name in ("正文写法", "来源与发布"):
        value = configured.get(name) if isinstance(configured, dict) else None
        if not value:
            die(f"缺少 contracts.{name} 配置；请先提供项目自己的处理与发布契约。")
        p = kb_path(value)
        if not p.is_file():
            die(f"契约文件不存在：{name}。")
        result[name] = p
    return result


def required_extractor(default="public-v1"):
    return str(CONFIG.get("extractor_version", default))


def rework_status_path():
    hits = sorted(SCRATCH.glob("可读性返工_*/返工状态.json"))
    return hits[-1] if hits else None


def formal_masters():
    """优先读取显式 masters 配置，否则解析用户自己的权威索引。"""
    configured = CONFIG.get("masters")
    if configured is not None:
        if not isinstance(configured, dict):
            die("masters 必须是 tactics、insights、method 的路径映射。")
        out = {k: kb_path(v) for k, v in configured.items() if k in SOT_ROWS}
    else:
        if not SOT.is_file():
            die("未找到 SOURCE_OF_TRUTH.md，且没有配置 masters。")
        text = SOT.read_text(encoding="utf-8")
        out = {}
        for kind, label in SOT_ROWS.items():
            m = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|\s*`([^`]+)`", text, re.M)
            if m:
                p = (SOT.parent / m.group(1)).resolve()
                if not p.is_relative_to(KB):
                    die("SOURCE_OF_TRUTH 中的母版必须位于知识库内。")
                out[kind] = p
    missing = [k for k in SOT_ROWS if k not in out or not out[k].is_file()]
    if missing:
        die("缺少可读取的母版：" + "、".join(missing) + "。格式见 README.md。")
    return out


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def snapshot_masters():
    """开轮时固定母版：路径加哈希。一轮之内母版换了版本，候选仍按这份快照定位。"""
    return {k: {"path": str(p), "sha256": sha256(p)} for k, p in formal_masters().items() if p.exists()}


def run_master(run, kind):
    """读运行目录记录的母版快照；旧格式（只存路径）也兼容。返回 (路径, 记录的哈希或 None)。"""
    m = (load_json(Path(run) / RUN_STATE_NAME, {}).get("masters") or {}).get(kind)
    if isinstance(m, dict):
        return Path(m["path"]), m.get("sha256")
    return (Path(m), None) if m else (None, None)


def master_path(kind, override=None, run=None):
    """--file 优先；给了运行目录就用开轮快照；否则读 SOURCE_OF_TRUTH 当前登记。"""
    if override:
        return Path(override).resolve()
    if run:
        p, recorded = run_master(run, kind)
        if p is None:
            die(f"运行目录没有记录{KIND_ZH[kind]}母版")
        if not p.exists():
            die(f"开轮时的{KIND_ZH[kind]}母版已不存在：{p}")
        if recorded and sha256(p) != recorded:
            print(f"注意：{KIND_ZH[kind]}母版在开轮后被原地改动过，定位结果可能和子代理看到的不同", file=sys.stderr)
        return p
    p = formal_masters().get(kind)
    if not p:
        die(f"SOURCE_OF_TRUTH 里没找到「{SOT_ROWS[kind]}」这一行")
    if not p.exists():
        die(f"SOURCE_OF_TRUTH 登记的{KIND_ZH[kind]}母版不存在：{p}")
    return p


def master_drift(run):
    """开轮快照与 SOURCE_OF_TRUTH 当前登记不一致的种类。"""
    now = formal_masters()
    out = []
    for kind in SOT_ROWS:
        p, _ = run_master(run, kind)
        if p and now.get(kind) and Path(p).resolve() != now[kind]:
            out.append((kind, p, now[kind]))
    return out


def probe_lock():
    """非阻塞试拿发布锁后立即释放。返回 True 表示当前没人持有。"""
    if not LOCK.exists():
        return True
    with LOCK.open("r+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fh, fcntl.LOCK_UN)
    return True


def new_run_dir(now=None):
    now = now or datetime.now()
    d = SCRATCH / f"增量挖掘_{now:%Y-%m-%d}" / f"运行_{now:%H%M%S}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def resolve_run(arg=None):
    """--run 未给时，取最近一个由 run_init.py 建立的运行目录。"""
    if arg:
        d = Path(arg).resolve()
        if not (d / RUN_STATE_NAME).exists():
            die(f"{d} 不是 run_init.py 建立的运行目录")
        return d
    hits = sorted(SCRATCH.glob(f"增量挖掘_*/运行_*/{RUN_STATE_NAME}"))
    if not hits:
        die("还没有运行目录，先跑 run_init.py")
    return hits[-1].parent


def in_run(run, name):
    """运行收尾时常把过程文件挪进 制作过程/，两处都找；都没有时返回顶层路径。"""
    for p in (Path(run) / name, Path(run) / "制作过程" / name):
        if p.exists():
            return p
    return Path(run) / name


def load_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def dump_json(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def short(s, n=60):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def rel(p):
    return os.path.relpath(str(p), str(ROOT))


def fmt_size(n):
    return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{n/1024:.0f} KB"
