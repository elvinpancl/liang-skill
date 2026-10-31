"""公开配置和增量扫描的合成数据回归；不接触真实知识库或网络。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class PublicConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.kb = Path(self.temp.name)
        self.env = dict(os.environ, LIANG_KB_ROOT=str(self.kb), PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("LIANG_TRANSCRIPT_CONFIG", None)
        self.config = {"source_patterns": ["sources/*.txt"], "masters": {}, "contracts": {}}
        for kind in ("tactics", "insights", "method"):
            (self.kb / (kind + ".md")).write_text("# 合成测试母版\n", encoding="utf-8")
            self.config["masters"][kind] = kind + ".md"
        for name in ("正文写法", "来源与发布"):
            (self.kb / (name + ".md")).write_text("仅用于合成测试，不授权云端发布。", encoding="utf-8")
            self.config["contracts"][name] = name + ".md"
        self.save()

    def save(self):
        (self.kb / "liang-transcript.json").write_text(json.dumps(self.config), encoding="utf-8")

    def run_script(self, script, *args, env=None):
        return subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *args], env=env or self.env,
                              text=True, capture_output=True)

    def test_missing_configuration_fails_without_writes(self):
        env = dict(self.env)
        env.pop("LIANG_KB_ROOT")
        r = self.run_script("run_init.py", "--status", env=env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("LIANG_KB_ROOT", r.stderr)
        self.assertFalse((self.kb / "直播录音资料").exists())

    def test_status_is_read_only_and_first_run_is_candidate(self):
        r = self.run_script("run_init.py", "--status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("本轮模式：候选", r.stdout)
        self.assertFalse((self.kb / "直播录音资料").exists())

    def test_missing_master_is_reported(self):
        (self.kb / "method.md").unlink()
        r = self.run_script("run_init.py", "--status")
        self.assertEqual(r.returncode, 2)
        self.assertIn("method", r.stderr)

    def test_scanner_tracks_new_changed_stale_and_skips_symlinks(self):
        sources = self.kb / "sources"
        sources.mkdir()
        (sources / "new.txt").write_text("新增合成来源", encoding="utf-8")
        (sources / "changed.txt").write_text("修改后的合成来源", encoding="utf-8")
        stale = sources / "stale.txt"
        stale.write_text("旧标准合成来源", encoding="utf-8")
        (sources / "alias.txt").symlink_to(stale)
        state = self.kb / "直播录音资料/scratchpad/定时更新"
        state.mkdir(parents=True)
        baseline = "relative_path\tsha256\textractor_version\n"
        baseline += "../sources/changed.txt\t" + "0" * 64 + "\tpublic-v1\n"
        baseline += "../sources/stale.txt\t" + hashlib.sha256(stale.read_bytes()).hexdigest() + "\told\n"
        (state / "processed_source_hashes.tsv").write_text(baseline, encoding="utf-8")
        r = self.run_script("check_source_increment.py", "--require", "public-v1")
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result["new"], ["../sources/new.txt"])
        self.assertEqual(result["changed"], ["../sources/changed.txt"])
        self.assertEqual(result["stale"], ["../sources/stale.txt"])
        self.assertEqual(result["scanned"], 3)
        self.assertEqual((state / "processed_source_hashes.tsv").read_text(), baseline)

    def test_getnote_missing_configuration_fails_before_network(self):
        r = self.run_script("getnote_fetch.py", "list")
        self.assertEqual(r.returncode, 2)
        self.assertIn("getnote.topic_id", r.stderr)

    def test_queue_works_with_bundled_scanner(self):
        (self.kb / "sources").mkdir()
        (self.kb / "sources/one.txt").write_text("这是测试来源，不是真实业务证据。", encoding="utf-8")
        r = self.run_script("run_init.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_script("source_queue.py", "build")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_script("source_queue.py", "next", "--n", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Q001", r.stdout)


if __name__ == "__main__":
    unittest.main()
