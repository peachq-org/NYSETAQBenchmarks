"""tools/publish.sh and pysrc/publishData.py on a hand-made two-solution run.

    python -m unittest discover -s test/publish
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ("solution|storagebackend|compparam|threadcount|runner|engine|format|indexon|idx|query|status|"
          "run1timeNS|run2timeNS|run3timeNS|run3memKB|run1ioKB|run2ioKB|run3ioKB|ressizeKB")
ENVIRONMENT = """test date: "2026-10-23"
test time: "12:00:00"
parameters:
  datadate: "20260701"
system:
  os:
    name: "Linux"
    kernel: "6.8.0"
  cpu:
    Model: "12th Gen Intel(R) Core(TM) i7-12700H"
  memory:
    TotalGB: 35
"""
KX_MARKS = ("kx-logo", "GTM-", "googletagmanager", "©", "KX®", "kx.com", "OneTrust", "Cookie Settings",
            "#FFCB22", "#D5A600", "#2159B2", "#3272D9", "#A8C5F0")


def row(solution, idx, status, ns, runner="Python", engine="duckdb_con"):
    times = "|".join(str(ns) for _ in range(3)) if ns else "||"
    return f"{solution}|memory|nyi|1|{runner}|{engine}||sym|{idx}|query {idx}|{status}|{times}|0|||"


def load_js(path, prefix):
    text = path.read_text()
    return json.loads(text[text.index(prefix) + len(prefix):].strip().rstrip(";"))


class PublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="publish-test-")
        cls.addClassCleanup(temp.cleanup)
        cls.temp = Path(temp.name)
        run = cls.temp / "results" / "run"
        run.mkdir(parents=True)
        (run / "environment.yaml").write_text(ENVIRONMENT)
        rows = [HEADER, row("DuckDB (Index)", 0, "success", 5_000_000)]
        rows += [row("DuckDB (Index)", i, "success", 2_000_000) for i in (1, 2, 3)]
        rows += [row("qlite", 0, "success", 7_000_000, "qlite", "q-sql"),
                 row("qlite", 1, "success", 1_000_000, "qlite", "q-sql"),
                 row("qlite", 2, "success", 1_500_000, "qlite", "q-sql"),
                 row("qlite", 3, "timeout", 9_000_000, "qlite", "q-sql")]
        (run / "results.psv").write_text("\n".join(rows) + "\n")
        for name, folder in (("DuckDB (Index)", "DuckDB_Index_"), ("qlite", "qlite")):
            (run / folder).mkdir()
            (run / folder / "stats.yaml").write_text(f"solution: {name}\nproprietary: 'no'\nengineversion: 1.0\n")
        cls.verdicts = cls.temp / "verdicts.tsv"
        cls.verdicts.write_text("solution\tidx\tverdict\n"
                                "DuckDB (Index)\t1\tok\nDuckDB (Index)\t2\tok\nDuckDB (Index)\t3\tok\n"
                                "qlite\t1\tok\nqlite\t2\twrong\nqlite\t3\tok\n")
        cls.stage = cls.temp / "stage"
        cls.out = subprocess.run([sys.executable, str(ROOT / "pysrc/publishData.py"), str(cls.temp / "results"),
                                  str(cls.stage), "--size", "tiny", "--verdicts", str(cls.verdicts)],
                                 cwd=ROOT, capture_output=True, text=True)

    def setUp(self):
        self.assertEqual(self.out.returncode, 0, self.out.stderr)

    def test_only_ok_verdicts_keep_their_timing(self):
        data = load_js(self.stage / "data.js", "window.PEACHQ_BENCHMARK =")
        self.assertTrue(data["verified"])
        self.assertEqual(data["times"]["peachq"]["1"][:3], [1.0, None, None])
        self.assertEqual(data["times"]["DuckDB (Index)"]["1"][:3], [2.0, 2.0, 2.0])
        self.assertEqual(len(data["times"]["peachq"]["1"]), len(data["queries"]))
        self.assertEqual(data["setup"]["peachq"]["1"]["load"], 7.0)
        self.assertEqual(data["datadate"], "2026-07-01")
        self.assertEqual(data["history"], [])

    def test_drill_down_drops_the_same_cells(self):
        generated = (self.stage / "full/results/inmemory/tiny/data.generated.js").read_text()
        entry = next(json.loads(line.lstrip(",")) for line in generated.splitlines()
                     if '"solution":"peachq"' in line)
        self.assertEqual(entry["result"]["1"], [[1000000] * 3, [None] * 3, [None] * 3])

    def test_mixed_numa_settings_are_refused(self):
        tree = self.temp / "numa"
        for name, node in (("unpinned", ""), ("pinned", "0")):
            run = tree / name
            run.mkdir(parents=True)
            (run / "environment.yaml").write_text(ENVIRONMENT + f'envvars:\n  NUMANODE: "{node}"\n')
            (run / "results.psv").write_text(HEADER + "\n" + row("DuckDB (Index)", 1, "success", 1) + "\n")
        done = subprocess.run([sys.executable, str(ROOT / "pysrc/publishData.py"), str(tree), str(self.temp / "s2"),
                               "--size", "tiny", "--unverified"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("NUMA", done.stderr)

    def test_go_refuses_without_verdicts(self):
        stage = self.temp / "refused"
        env = dict(os.environ, GO="1", PEACHQ_HOST="nobody@invalid.invalid", PYTHON=sys.executable)
        for gate in ([], ["--unverified"]):
            done = subprocess.run(["bash", "tools/publish.sh", "--results", str(self.temp / "results"),
                                   "--size", "tiny", "--stage", str(stage), *gate],
                                  cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 1, done.stderr)
            self.assertIn("refusing GO=1 without a verdicts file", done.stderr)
            self.assertFalse(stage.exists())

    def test_local_preview_is_stamped_unverified(self):
        local = self.temp / "site/data/benchmark"
        env = dict(os.environ, PYTHON=sys.executable)
        done = subprocess.run(["bash", "tools/publish.sh", "--results", str(self.temp / "results"), "--size", "tiny",
                               "--unverified", "--stage", str(self.temp / "stage-local"), "--local", str(local)],
                              cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(load_js(local / "data.js", "window.PEACHQ_BENCHMARK =")["verified"])
        self.assertTrue((local / "full/index.html").is_file())

    def test_drill_down_carries_no_kx_mark(self):
        for path in (self.stage / "full").rglob("*"):
            if path.suffix in (".html", ".css", ".js"):
                text = path.read_text().lower()
                for mark in KX_MARKS:
                    self.assertNotIn(mark.lower(), text, f"{mark} in {path}")
        html = (self.stage / "full/index.html").read_text()
        self.assertIn("github.com/KxSystems/NYSETAQBenchmarks", html)
        self.assertTrue(re.search(r"--chart-scale-1: #f28b57", (self.stage / "full/assets/css/benchmark.css")
                                  .read_text()))


if __name__ == "__main__":
    unittest.main()
