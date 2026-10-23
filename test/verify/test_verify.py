"""Unit tests for pysrc/verify: python -m unittest discover -s test/verify (from the repo root)."""
import argparse
import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pysrc" / "verify"))

import canon  # noqa: E402
import main  # noqa: E402
from compare import OK, ORDER_ONLY, SHAPE_DIFF, VALUE_DIFF, compare  # noqa: E402
from consensus import decide  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def table(text: str) -> canon.Canon:
    return canon.canonical(pl.read_csv(io.StringIO(text), infer_schema=False))


def verdict(a: str, b: str, order=None, rtol=None) -> str:
    return compare(table(a), table(b), order, rtol or {}).verdict


def verify(outputs: Path, **extra) -> dict:
    """Runs verify on a fixture panel and returns solution -> verdict for its one query."""
    with tempfile.TemporaryDirectory() as tmp:
        args = argparse.Namespace(outputs=str(outputs), results=[], param_dir=str(ROOT / "artifacts/parameters/test"),
                                  datadate="20260401", size="test", querymeta=str(ROOT / main.solutions.QUERIES /
                                                                                  "querymeta.psv"),
                                  float32=str(ROOT / "artifacts/verification/float32.psv"), golden_root=tmp,
                                  report=tmp, ledger="", idx="20", reference=None, queryset="kx")
        vars(args).update(extra)
        with contextlib.redirect_stdout(io.StringIO()):
            main.run(args)
        with open(Path(tmp) / "verdicts.tsv") as f:
            return {r["solution"]: r["verdict"] for r in csv.DictReader(f, delimiter="\t")}


class FalsifyingRow(unittest.TestCase):
    """idx 20 with DuckDB's IEEE division on: DuckDB answers NaN, six other implementations a number."""

    def test_consensus_marks_only_duckdb(self):
        got = verify(FIXTURES / "idx20")
        self.assertEqual(got.pop("DuckDB (Index)"), VALUE_DIFF)
        self.assertEqual(set(got.values()), {OK}, got)
        self.assertEqual(len(got), 6)

    def test_duckdb_as_reference_marks_the_six_correct_engines(self):
        got = verify(FIXTURES / "idx20", reference="DuckDB (Index)")
        self.assertEqual(got.pop("DuckDB (Index)"), OK)
        self.assertEqual(set(got.values()), {VALUE_DIFF}, got)


class FalsifyingExtraRow(unittest.TestCase):
    """idx 109 of the common workloads, with Polars' realised volatility taken as the sample deviation (std(), not
    std(ddof=0)): five other implementations answer the population one."""

    def test_consensus_marks_only_the_sample_deviation(self):
        got = verify(FIXTURES / "idx109", queryset="extra", idx="109", param_dir=str(ROOT / "artifacts/parameters/tiny"),
                     datadate="20260701", size="tiny", querymeta=None)
        self.assertEqual(got.pop("Polars (Eager)"), VALUE_DIFF)
        self.assertEqual(got, dict.fromkeys(["DuckDB (Index)", "Pandas", "chDB (Memory)", "l", "peachq"], OK))


class CanonicalForm(unittest.TestCase):
    def test_q_blank_char_equals_empty(self):
        self.assertEqual(verdict('sym,cond\nA," "\n', 'sym,cond\nA,""\n'), OK)
        self.assertEqual(verdict("sym,cond\nA, \n", "sym,cond\nA,\n"), OK)

    def test_every_null_spelling_is_one_null(self):
        spellings = ["", " ", "0n", "0N", "0Nj", "0Ne", "-nan", "nan", "NaN", "null"]
        for s in spellings:
            self.assertEqual(verdict(f"k,v\n1,{s}\n2,1.5\n", "k,v\n1,\n2,1.5\n"), OK, s)
        self.assertEqual(verdict("k,v\n1,nan\n", "k,v\n1,0.0\n"), VALUE_DIFF)

    def test_timestamps(self):
        q, duck = "t\n0D09:32:06.999999533\n", "t\n09:32:06.999999533\n"
        self.assertEqual(verdict(q, duck), OK)
        self.assertEqual(verdict(q, "t\n34326999999533\n"), OK)
        self.assertEqual(verdict(q, "t\n09:32:07.999999533\n"), VALUE_DIFF)
        self.assertEqual(verdict("m\n03:50\n", "m\n03:50:00.000000000\n"), OK)
        self.assertEqual(verdict("k,t\n1,0D00:00:00.000000000\n", "k,t\n1,\n"), VALUE_DIFF)

    def test_booleans_and_widened_integers(self):
        self.assertEqual(verdict("b\ntrue\nfalse\n", "b\n1\n0\n"), OK)
        self.assertEqual(verdict("b\n1b\n0b\n", "b\n1\n0\n"), OK)
        self.assertEqual(verdict("n\n100\n", "n\n100.0\n"), OK)

    def test_text_trimmed_names_exact_order_ignored(self):
        self.assertEqual(verdict("a,b\n x,1\n", "b,a\n1,x \n"), OK)
        self.assertEqual(verdict("a,b\nx,1\n", "a,B\nx,1\n"), SHAPE_DIFF)
        self.assertEqual(verdict("a\nx\n", "a\nx\nx\n"), SHAPE_DIFF)


class Floats(unittest.TestCase):
    def test_relative_tolerance_with_floor(self):
        self.assertEqual(verdict("v\n4623334752.252007\n", "v\n4623334748.141113\n"), OK)
        self.assertEqual(verdict("v\n1.0\n", "v\n1.000002\n"), VALUE_DIFF)
        self.assertEqual(verdict("v\n0.0\n", "v\n1e-10\n"), OK)
        self.assertEqual(verdict("v\n0.0\n", "v\n1e-8\n"), VALUE_DIFF)

    def test_infinities_match_only_themselves(self):
        self.assertEqual(verdict("v\n0w\n", "v\ninf\n"), OK)
        self.assertEqual(verdict("v\ninf\n", "v\n1.0\n"), VALUE_DIFF)
        self.assertEqual(verdict("v\ninf\n", "v\n-inf\n"), VALUE_DIFF)

    def test_q_real_printing_is_inside_the_base_tolerance(self):
        self.assertEqual(verdict("v\n266.667968\n", "v\n266.6679\n"), OK)

    def test_six_decimals_carry_their_rounding(self):
        self.assertEqual(verdict("v\n0.120348\n", "v\n0.12034784226603915\n"), OK)
        self.assertEqual(verdict("v\n0.001235\n", "v\n0.0012345001\n"), OK)
        self.assertEqual(verdict("v\n0.001236\n", "v\n0.0012345001\n"), VALUE_DIFF)
        self.assertEqual(verdict("v\n0.5\n", "v\n0.501\n"), VALUE_DIFF)

    def test_float32_allowance_only_where_documented(self):
        duck, others = "s\n0.013049532\n", "s\n0.013049617\n"
        self.assertEqual(verdict(duck, others), VALUE_DIFF)
        self.assertEqual(verdict(duck, others, rtol={"s": 1e-5}), OK)
        self.assertEqual(verdict(duck, others, rtol={"other": 1e-5}), VALUE_DIFF)
        polars_std = "s\n0.0289\n"
        self.assertEqual(verdict(polars_std, "s\n0.0491\n", rtol={"s": 1e-5}), VALUE_DIFF)
        allowed = main.float32_allowance(ROOT / "artifacts/verification/float32.psv")
        self.assertIn("avgWeightedSpread", allowed[41])
        self.assertNotIn(20, allowed)


class Order(unittest.TestCase):
    tie = "time,mid\n09:30,1.5\n09:30,2.5\n"
    swapped = "time,mid\n09:30,2.5\n09:30,1.5\n"

    def test_tie_order_is_not_an_answer_unless_sort_tagged(self):
        self.assertEqual(verdict(self.tie, self.swapped), OK)
        self.assertEqual(verdict(self.tie, self.swapped, order=["mid", "time"]), ORDER_ONLY)
        self.assertEqual(verdict(self.tie, "time,mid\n09:30,2.5\n09:30,1.6\n", order=["mid", "time"]), VALUE_DIFF)

    def test_a_sort_key_tied_within_tolerance_leaves_its_rows_unordered(self):
        q = "mid,time\n31.2450005,09:46\n31.2450001,19:59\n"
        duck = "mid,time\n31.245,19:59\n31.245,09:46\n"
        self.assertEqual(verdict(duck, q, order=["mid", "time"]), OK)
        self.assertEqual(verdict("mid,time\n31.3,19:59\n31.2,09:46\n", "mid,time\n31.2,09:46\n31.3,19:59\n",
                                 order=["mid", "time"]), ORDER_ONLY)


class Ties(unittest.TestCase):
    def test_floats_tied_within_tolerance_on_equal_keys_match_in_either_order(self):
        duck = "sym,time,m,s\nZ,1,26.656667,160\nZ,1,26.656667,100\nZ,2,26.6,200\n"
        ray = "sym,time,m,s\nZ,1,26.65666675,100\nZ,1,26.65666670,160\nZ,2,26.6,200\n"
        self.assertEqual(verdict(duck, ray), OK)
        self.assertEqual(verdict(duck, ray.replace("100", "101")), VALUE_DIFF)


class Consensus(unittest.TestCase):
    def decide(self, answers: dict):
        impl = {"pl-lazy": "polars", "pl-eager": "polars"}
        return decide({n: table(t) for n, t in answers.items()}, lambda n: impl.get(n, n), None, {})

    def test_one_implementation_is_one_vote(self):
        out = self.decide({"pl-lazy": "v\n1\n", "pl-eager": "v\n1\n", "duck": "v\n1\n", "ch": "v\n2\n", "pd": "v\n2\n"})
        self.assertIsNone(out.golden)
        self.assertIn("no majority", out.evidence)

    def test_majority_of_three(self):
        out = self.decide({"a": "v\n1\n", "b": "v\n1\n", "c": "v\n1\n", "d": "v\n2\n", "e": "v\n3\n"})
        self.assertEqual(sorted(out.agreeing), ["a", "b", "c"])

    def test_every_agreeing_solution_was_compared_with_the_golden(self):
        answers = {"a": "v\n1.000001\n", "b": "v\n1.0\n", "c": "v\n1.0000021\n"}
        out = self.decide(answers)
        golden = out.golden
        for n in out.agreeing:
            self.assertEqual(compare(golden, table(answers[n]), None, {}).verdict, OK, n)

    def test_kdb_variants_are_one_implementation(self):
        self.assertEqual({main.solutions.implementation(s) for s in main.solutions.SOLUTIONS if "KDB" in s or s == "pykx"},
                         {"kdb"})

    def test_more_must_agree_than_disagree(self):
        out = self.decide({"a": "v\n1\n", "b": "v\n1\n", "c": "v\n1\n", "d": "v\n2\n", "e": "v\n2\n", "f": "v\n3\n"})
        self.assertIsNone(out.golden)


if __name__ == "__main__":
    unittest.main()
