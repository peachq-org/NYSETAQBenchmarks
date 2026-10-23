# /// script
# requires-python = ">=3.10"
# dependencies = ["polars>=1.35", "pyyaml"]
# ///
"""Checks every solution's query outputs against a consensus golden and records the result.

See docs/verification.md for the canonical form, the tolerances and the consensus rule this implements.
"""
import argparse
import csv
import datetime
import hashlib
import subprocess
import sys
import time
from pathlib import Path

import polars as pl
import yaml

import canon
import solutions
from compare import MISSING, NOT_WRITTEN, OK, ORDER_ONLY, SHAPE_DIFF, UNRESOLVED, VALUE_DIFF, Verdict
from consensus import decide, from_frame, judge, unresolved

FAILS = (VALUE_DIFF, SHAPE_DIFF, ORDER_ONLY, MISSING)
LEDGER_COLUMNS = ["verified", "solution", "implementation", "engineversion", "queryfile", "queryhash", "paramhash",
                  "datadate", "size", "ok", "fail", "unresolved", "notwritten", "queries", "commit"]


def parse_idx(spec: str) -> set:
    """The runners' -idx forms, as pysrc/queryrunner/main.py's parse_idx_filter reads them; not imported from
    there, because that would make the verifier load a runner and its dependencies."""
    picked = set()
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        picked.update(range(int(lo), int(hi or lo) + 1))
    return picked


def read_psv(path: Path) -> list:
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="|"))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def dir_hash(d: Path) -> str:
    return sha(b"".join(p.name.encode() + b"\0" + p.read_bytes() for p in sorted(d.iterdir()) if p.is_file()))


def output_file(d: Path, idx: int):
    return next((p for p in (d / f"queryoutput_{idx}.csv", d / f"queryoutput_{idx}.csv.zst") if p.exists()), None)


class Solution:
    """One per-solution output directory, named back to its solution through its run's stats.yaml."""

    def __init__(self, out_dir: Path, result_dirs: list):
        self.dir = out_dir
        stats = next((r / out_dir.name / "stats.yaml" for r in result_dirs if (r / out_dir.name / "stats.yaml").exists()),
                     None)
        meta = yaml.safe_load(stats.read_text()) if stats else {}
        self.name = meta.get("solution") or solutions.BY_DIR.get(out_dir.name, out_dir.name)
        self.version = str(meta.get("engineversion", "unknown"))
        self.implementation = solutions.implementation(self.name)
        self.query_file = solutions.query_file(self.name)
        self.status = {}
        for r in result_dirs:
            if (r / "results.psv").exists():
                self.status.update({int(row["idx"]): row["status"] for row in read_psv(r / "results.psv")
                                    if row["solution"] == self.name})
        self.written = None
        if self.query_file and Path(self.query_file).exists():
            self.written = {int(row["idx"]) for row in read_psv(Path(self.query_file)) if row["query"].strip()}

    def answer(self, idx: int):
        """A Canon, or the Verdict standing in for an output that is not there."""
        if self.written is not None and idx not in self.written or self.status.get(idx) == "emptyquery":
            return Verdict(NOT_WRITTEN, "no query at this idx")
        path = output_file(self.dir, idx)
        if path is None:
            return Verdict(MISSING, f"status {self.status.get(idx, 'unknown')!r}"[:200])
        try:
            return canon.read(path)
        except Exception as e:
            return Verdict(SHAPE_DIFF, f"unreadable: {e}"[:200])


def float32_allowance(path: Path) -> dict:
    """idx -> {column: rtol} from the committed allowance table."""
    allowed = {}
    for row in read_psv(path) if path.exists() else []:
        allowed.setdefault(int(row["idx"]), {})[row["column"]] = float(row["rtol"])
    return allowed


def golden_path(root: Path, idx: int) -> Path:
    return root / f"golden_{idx}.parquet"


def run(args) -> int:
    started = time.time()
    wanted = parse_idx(args.idx) if args.idx else None
    meta = [row for row in read_psv(Path(args.querymeta)) if wanted is None or int(row["idx"]) in wanted]
    result_dirs = [Path(r) for r in args.results]
    # run_solution creates every attempted solution's directory, so an empty one is a solution that answered nothing.
    panel = [Solution(d, result_dirs) for d in sorted(Path(args.outputs).iterdir()) if d.is_dir()]
    if not panel:
        sys.exit(f"no solution directories under {args.outputs}")
    names = [s.name for s in panel]
    impl = {s.name: s.implementation for s in panel}
    allowance = float32_allowance(Path(args.float32))
    paramhash = dir_hash(Path(args.param_dir))
    size = args.size or Path(args.param_dir).name
    golden_root = Path(args.golden_root) / f"{size}_{args.datadate}_{paramhash}"
    if not args.reference:
        golden_root.mkdir(parents=True, exist_ok=True)

    rows, manifest = [], []
    for q in meta:
        idx = int(q["idx"])
        order = q["sortby"].split(",") if "sort" in q["tags"].split(",") else None
        rtol = allowance.get(idx, {})
        answers, verdicts = {}, {}
        for s in panel:
            a = s.answer(idx)
            (verdicts if isinstance(a, Verdict) else answers)[s.name] = a
        if args.reference:
            ref = answers.get(args.reference)
            verdicts.update(judge(ref, answers, [], order, rtol) if ref else
                            unresolved(answers, f"reference {args.reference} has no answer"))
            source = args.reference
        else:
            outcome = decide(answers, impl.get, order, rtol)
            stored = golden_path(golden_root, idx)
            if outcome.golden is not None:
                outcome.golden.frame.write_parquet(stored, compression="zstd")
                verdicts.update(judge(outcome.golden, answers, outcome.agreeing, order, rtol))
                source = "consensus"
            elif stored.exists():
                verdicts.update(judge(from_frame(pl.read_parquet(stored)), answers, [], order, rtol))
                source = "stored"
            else:
                verdicts.update(unresolved(answers, outcome.evidence))
                source = "unresolved"
            manifest.append({"idx": idx, "golden": source, "agreeing": ",".join(outcome.agreeing),
                             "evidence": outcome.evidence})
        for n in names:
            rows.append({"solution": n, "idx": idx, "verdict": verdicts[n].verdict, "evidence": verdicts[n].evidence})
        print(f"{idx:>3} {source:<10} " + " ".join(f"{n}={verdicts[n].verdict}" for n in names
                                                   if verdicts[n].verdict != OK), flush=True)

    report = Path(args.report or (result_dirs[0] / "verification" if result_dirs else
                                  f"results/verification/{size}_{args.datadate}"))
    report.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).select("solution", "idx", "verdict").write_csv(report / "verdicts.tsv", separator="\t")
    pl.DataFrame(rows).write_csv(report / "verdicts.psv", separator="|")
    if manifest:
        pl.DataFrame(manifest).write_csv(golden_root / "manifest.psv", separator="|")

    counts = pl.DataFrame(rows).group_by("solution", "verdict").len().pivot("verdict", index="solution", values="len") \
        .fill_null(0).sort("solution")
    print(counts)
    print(f"verified {len(meta)} queries x {len(panel)} solutions in {time.time() - started:.0f}s; "
          f"verdicts in {report}")
    if not args.reference and args.ledger:
        record(Path(args.ledger), panel, rows, paramhash, args.datadate, size, len(meta))
    return 0 if all(r["verdict"] in (OK, NOT_WRITTEN) for r in rows) else 1


def record(ledger: Path, panel: list, rows: list, paramhash: str, datadate: str, size: str, queries: int):
    """Upserts one row per solution, keyed on what makes a verification stale."""
    key = ("solution", "engineversion", "queryhash", "paramhash", "datadate", "size")
    kept = read_psv(ledger) if ledger.exists() else []
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    today = datetime.date.today().isoformat()
    for s in panel:
        mine = [r["verdict"] for r in rows if r["solution"] == s.name]
        entry = {"verified": today, "solution": s.name, "implementation": s.implementation,
                 "engineversion": s.version, "queryfile": s.query_file or "unknown",
                 "queryhash": sha(Path(s.query_file).read_bytes()) if s.query_file else "unknown",
                 "paramhash": paramhash, "datadate": datadate, "size": size, "ok": mine.count(OK),
                 "fail": sum(mine.count(v) for v in FAILS), "unresolved": mine.count(UNRESOLVED),
                 "notwritten": mine.count(NOT_WRITTEN), "queries": queries, "commit": commit}
        kept = [r for r in kept if tuple(r[k] for k in key) != tuple(str(entry[k]) for k in key)] + [entry]
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "w", newline="") as f:
        w = csv.DictWriter(f, LEDGER_COLUMNS, delimiter="|", lineterminator="\n")
        w.writeheader()
        w.writerows(kept)
    print(f"ledger: {len(panel)} row(s) in {ledger}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-q", "--query-output-dir", required=True, dest="outputs",
                    help="as given to queryEngines.sh: one subdirectory of queryoutput_<idx>.csv[.zst] per solution")
    ap.add_argument("-r", "--result-dir", action="append", default=[], dest="results",
                    help="as given to queryEngines.sh: holds <solution>/stats.yaml and results.psv; repeatable")
    ap.add_argument("-p", "--param-dir", required=True)
    ap.add_argument("-d", "--datadate", required=True)
    ap.add_argument("--size", help="default: the --param-dir basename")
    ap.add_argument("--querymeta", default="artifacts/queries/inmemory/querymeta.psv")
    ap.add_argument("--float32", default="artifacts/verification/float32.psv")
    ap.add_argument("--golden-root", default="DATA/verification")
    ap.add_argument("--report", help="default: <first --result-dir>/verification, else results/verification/<size>_<datadate>")
    ap.add_argument("--ledger", default="artifacts/verification/ledger.psv", help="'' to not record")
    ap.add_argument("-i", "--idx", help="42, 32,42,50 or 40-44")
    ap.add_argument("--reference", help="compare against this solution instead of the consensus; records nothing")
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
