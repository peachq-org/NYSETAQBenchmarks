"""tools/publish.sh and pysrc/publishData.py on a hand-made two-solution run.

    python -m unittest discover -s test/publish
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pysrc"))
from publishData import prices_of, speeds  # noqa: E402
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


PRICE_COLUMN = "trade:\n  columns:\n  - name: price\n    type: {}\n    attr:\n"


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
        rows += [row("Polars (Eager)", i, "success", 3_000_000, engine="polars") for i in (1, 2, 3)]
        (run / "results.psv").write_text("\n".join(rows) + "\n")
        for name, folder in (("DuckDB (Index)", "DuckDB_Index_"), ("qlite", "qlite"), ("Polars (Eager)", "Polars_Eager_")):
            (run / folder).mkdir()
            (run / folder / "stats.yaml").write_text(f"solution: {name}\nproprietary: 'no'\nengineversion: 1.0\n")
        with (run / "qlite" / "stats.yaml").open("a") as fh:
            fh.write(f"binarysha256: {'ab' * 32}\n")
        with (run / "DuckDB_Index_" / "stats.yaml").open("a") as fh:
            fh.write(PRICE_COLUMN.format("DOUBLE"))
        cls.verdicts = cls.temp / "verdicts.tsv"
        cls.verdicts.write_text("solution\tidx\tverdict\n"
                                "DuckDB (Index)\t1\tok\nDuckDB (Index)\t2\tok\nDuckDB (Index)\t3\tok\n"
                                "qlite\t1\tok\nqlite\t2\twrong\nqlite\t3\tok\n"
                                "Polars (Eager)\t1\tok\nPolars (Eager)\t2\tok\nPolars (Eager)\t3\tok\n")
        cls.stage = cls.temp / "stage"
        cls.history = cls.temp / "history.psv"
        cls.out = cls.publish(cls.temp / "results", cls.stage)

    @classmethod
    def publish(cls, results, stage, *gate):
        return subprocess.run([sys.executable, str(ROOT / "pysrc/publishData.py"), str(results), str(stage),
                               "--size", "tiny", "--history", str(cls.history),
                               *(gate or ("--verdicts", str(cls.verdicts)))],
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
        # Polars (Eager) is not on the page, so queries 2 and 3 have only the target's time and are skipped.
        self.assertEqual(data["mph"]["peachq"]["1"],
                         {"mph": 200.0, "mphMedian": 200.0, "answered": 1, "failed": 0, "total": len(data["queries"])})
        self.assertEqual((data["target"], data["baselineVersion"]), ("DuckDB (Index)", "1.0"))

    def test_the_page_carries_only_its_solutions(self):
        data = load_js(self.stage / "data.js", "window.PEACHQ_BENCHMARK =")
        self.assertEqual([s["id"] for s in data["solutions"]], ["peachq", "DuckDB (Index)"])
        self.assertNotIn("Polars (Eager)", data["times"])
        self.assertIn('"solution":"Polars (Eager)"', (self.stage / "full/results/inmemory/tiny/data.generated.js")
                      .read_text())

    def test_history_records_a_run_once_and_a_new_target_version_as_a_new_series(self):
        again = self.publish(self.temp / "results", self.temp / "stage-again")
        self.assertEqual(again.returncode, 0, again.stderr)
        rows = load_js(self.temp / "stage-again/data.js", "window.PEACHQ_BENCHMARK =")["history"]
        self.assertEqual(len(rows), 1)
        self.assertEqual({k: rows[0][k] for k in ("date", "solution", "binarySha256", "target", "baselineVersion",
                                                  "threads", "prices", "mph", "answered", "failed")},
                         {"date": "2026-10-23", "solution": "peachq", "binarySha256": "ab" * 32,
                          "target": "DuckDB (Index)", "baselineVersion": "1.0", "threads": 1, "prices": "float64",
                          "mph": 200.0, "answered": 1, "failed": 0})

        bumped = self.temp / "bumped"
        shutil.copytree(self.temp / "results", bumped)
        stats = bumped / "run/DuckDB_Index_/stats.yaml"
        stats.write_text(stats.read_text().replace("engineversion: 1.0", "engineversion: 2.0"))
        done = self.publish(bumped, self.temp / "stage-bumped")
        self.assertEqual(done.returncode, 0, done.stderr)
        rows = load_js(self.temp / "stage-bumped/data.js", "window.PEACHQ_BENCHMARK =")["history"]
        self.assertEqual([r["baselineVersion"] for r in rows], ["1.0", "2.0"])
        self.assertEqual(len(self.history.read_text().splitlines()), 3)

        unverified = self.publish(bumped, self.temp / "stage-unverified", "--unverified")
        self.assertEqual(unverified.returncode, 0, unverified.stderr)
        self.assertEqual(len(self.history.read_text().splitlines()), 3)

    def test_the_data_note_follows_the_loaded_price_type(self):
        data = load_js(self.stage / "data.js", "window.PEACHQ_BENCHMARK =")
        self.assertEqual(data["prices"], "float64")
        self.assertIn("KxSystems/NYSETAQBenchmarks#25", data["dataNote"])
        self.assertIn("note: prices and sizes stored as float64", self.out.stdout)
        self.assertIn("Prices and sizes stored as float64; KX&#x27;s upstream uses float32",
                      (self.stage / "full/index.html").read_text())

        reals = self.temp / "reals"
        shutil.copytree(self.temp / "results", reals)
        stats = reals / "run/DuckDB_Index_/stats.yaml"
        stats.write_text(stats.read_text().replace("type: DOUBLE", "type: FLOAT"))
        done = self.publish(reals, self.temp / "stage-reals", "--unverified")
        self.assertEqual(done.returncode, 0, done.stderr)
        data = load_js(self.temp / "stage-reals/data.js", "window.PEACHQ_BENCHMARK =")
        self.assertEqual((data["prices"], data["dataNote"]), ("float32", ""))

        mixed = self.temp / "mixed"
        shutil.copytree(self.temp / "results", mixed / "a")
        shutil.copytree(reals, mixed / "b")
        psv = mixed / "b/run/results.psv"
        psv.write_text(psv.read_text().replace("DuckDB (Index)|memory|nyi|1|", "DuckDB (Index)|memory|nyi|4|"))
        done = self.publish(mixed, self.temp / "stage-mixed", "--unverified")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("publish one data set", done.stderr)

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
        done = self.publish(tree, self.temp / "s2", "--unverified")
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
                               "--unverified", "--stage", str(self.temp / "stage-local"), "--local", str(local),
                               "--history", str(self.temp / "no-history.psv")],
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


class PriceTypeTests(unittest.TestCase):
    def test_each_engine_spelling(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stats.yaml"
            for raw, want in (("FLOAT", "float32"), ("DOUBLE", "float64"), ("real", "float32"), ("float", "float64"),
                              ("Float32", "float32"), ("Float64", "float64"), ("float64", "float64"),
                              ("Nullable(Float32)", "float32"), ("'Nullable(Float64)'", "float64")):
                path.write_text("solution: x\n" + PRICE_COLUMN.format(raw))
                self.assertEqual(prices_of(path), want, raw)
            path.write_text("solution: x\n")
            self.assertEqual(prices_of(path), "")


class SpeedTests(unittest.TestCase):
    def test_mph_with_the_penalty_and_a_skipped_query(self):
        got = speeds({"DuckDB (Index)": [1, 2, 4, 1, None],
                      "A": [2, None, 4, None, 3],
                      "B": [0.5, 4, None, None, 1]}, "DuckDB (Index)")
        # Query 1: A missing, worst posted 4/2 -> A charged 4. Query 2: B missing, worst is the target's 1 -> 2.
        # Query 3: only the target answered, skipped. Query 4: no target time, skipped.
        self.assertEqual(got["A"], {"mph": 50.0, "mphMedian": 50.0, "answered": 3, "failed": 1, "total": 5})
        self.assertEqual(got["B"], {"mph": round(100 / 2 ** (1 / 3), 3), "mphMedian": 50.0, "answered": 3,
                                    "failed": 1, "total": 5})
        self.assertEqual(got["DuckDB (Index)"]["mph"], 100.0)


if __name__ == "__main__":
    unittest.main()
