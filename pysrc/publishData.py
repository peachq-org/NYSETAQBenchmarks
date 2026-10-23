#!/usr/bin/env python3
"""Stage benchmark results for peachq.org/benchmark.

    python pysrc/publishData.py RESULTS_DIR STAGE_DIR --size SIZE (--verdicts FILE | --unverified)

RESULTS_DIR holds run directories as ``benchmarks/inmemory/queryEngines.sh -r``
writes them: environment.yaml, results.psv and one ``<solution>/stats.yaml``
per solution. Three things are written under STAGE_DIR:

  results/  a filtered copy of the runs, the one input of both outputs below.
            Only the most recent run of each (solution, thread count) is kept,
            by environment.yaml "test date" then "test time". A query row whose
            status is not ``success``, or whose verdict is not ``ok``, has its
            three timings blanked: it is shown as absent, like a query the
            solution did not run. Solutions named before the rename (qlite,
            qlite (DuckDB)) take their current names.
  data.js   the summary the native page reads (schema below).
  full/     the drill-down: pysrc/convertToJSFormat.py over results/, then
            pysrc/buildSite.py.

The verdicts file comes from verify.sh: tab-separated, header
``solution<TAB>idx<TAB>verdict``, solution names as in results.psv. A
(solution, query) with no row is not verified and is dropped. --unverified
skips the verdict filter and stamps the data ``verified: false``; it exists for
dry runs and the local preview, and tools/publish.sh refuses to upload it.

data.js schema::

    window.PEACHQ_BENCHMARK = {
      updated:   "YYYY-MM-DD", the test date of the newest run included
      verified:  true | false
      machine:   {cpu, memGB, os}
      size:      the data size, e.g. "tiny"
      datadate:  "YYYY-MM-DD"
      baseline:  "DuckDB (Index)", the solution id ratios are taken against
      solutions: [{id, label, engine, version, threads: [1, 4], language, data, note}]
      queries:   [{idx, description, tags: [..]}], in idx order
      times:     {<solution id>: {<threads>: [warm ms or null, one per entry of queries]}}
      setup:     {<solution id>: {<threads>: {load, sort, index, store}}}, ms or null
      history:   [] for now; stage 2 fills it with one point per verified run:
                 {date, solution, version, binarySha256, baselineSolution: "l", baselineVersion,
                  threads, size, datadate, ratioGeomean, ratioMedian, answered, failed}
    }

A solution id is its results.psv name, so verdicts, the drill-down and the
page all key on one string. Warm ms is min(run2, run3). Setup times are run 1
of the load rows: load is idx 0 plus idx -1 (transform), sort -2, index -3,
store -4. Every run must come from one machine, one data date and one NUMA
setting; a mixed tree is refused rather than averaged. ``history`` is keyed by the date the run
happened plus the binary's sha256, never by version: peachq reuses release
numbers for different builds.
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from convertToJSFormat import cpu_model_of, numanode_of

ROOT = Path(__file__).resolve().parent.parent
QUERYMETA = ROOT / "artifacts" / "queries" / "inmemory" / "querymeta.psv"
BASELINE = "DuckDB (Index)"
RENAMED = {"qlite": "peachq", "qlite (DuckDB)": "peachq (via DuckDB)"}
TIMINGS = ("run1timeNS", "run2timeNS", "run3timeNS")
SETUP_PHASES = {0: "load", -1: "load", -2: "sort", -3: "index", -4: "store"}

PARQUET = "Parquet, loaded into memory"
SPLAYED = "splayed q database, loaded into memory"
SOLUTIONS = {
    "peachq": ("q", SPLAYED, "peachq running the kdb.psv qSQL queries"),
    "peachq (via DuckDB)": ("q", "splayed q database, stored in an in-memory DuckDB",
                            "the same qSQL, pushed down by peachq into DuckDB"),
    "l": ("q", SPLAYED, "a second q implementation on the same runner"),
    "Rayforce": ("Rayfall", "Rayforce splayed database, loaded into memory", "sorted by time, grouped index on sym"),
    "Rayforce Parted": ("Rayfall", "Rayforce splayed database, loaded into memory",
                        "sorted by sym and time, parted index on sym"),
    "DuckDB (Index)": ("SQL", PARQUET, "the baseline"),
    "Polars (Lazy)": ("Python", PARQUET, ""),
    "Polars (Eager)": ("Python", PARQUET, ""),
    "chDB (Memory)": ("SQL", PARQUET, ""),
    "Pandas": ("Python", PARQUET, ""),
}


def stamp(env):
    return str(env["test date"]), str(env.get("test time", ""))


def iso(datadate):
    d = str(datadate)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if re.fullmatch(r"\d{8}", d) else d


def read_psv(path):
    with path.open(newline="") as fh:
        header = fh.readline().rstrip("\n").split("|")
        rows = [dict(zip(header, line.rstrip("\n").split("|"))) for line in fh if line.strip()]
    return header, rows


def load_verdicts(path):
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames != ["solution", "idx", "verdict"]:
            raise SystemExit(f"publishData: {path} header must be solution<TAB>idx<TAB>verdict, "
                             f"got {reader.fieldnames}")
        return {(RENAMED.get(r["solution"], r["solution"]), int(r["idx"])): r["verdict"].strip() for r in reader}


def solution_dirs(run_dir):
    """Map each solution name to its stats directory, by the stats.yaml "solution" line."""
    found = {}
    for path in sorted(p for p in run_dir.iterdir() if (p / "stats.yaml").is_file()):
        m = re.search(r"^solution\s*:\s*(.+?)\s*$", (path / "stats.yaml").read_text(), re.M)
        if m:
            found[m.group(1).strip("'\"")] = path
    return found


def discover(results_dir):
    # followlinks: a tree assembled from symlinks to chosen run directories is the usual input.
    runs = sorted(Path(d) for d, _, files in os.walk(results_dir, followlinks=True)
                  if "environment.yaml" in files and "results.psv" in files)
    if not runs:
        raise SystemExit(f"publishData: no run (environment.yaml + results.psv) under {results_dir}")
    return [(run, yaml.safe_load((run / "environment.yaml").read_text())) for run in runs]


def newest_runs(runs):
    """(solution, threads) -> the run directory that measured it most recently."""
    chosen = {}
    for run, env in runs:
        _, rows = read_psv(run / "results.psv")
        for key in {(RENAMED.get(r["solution"], r["solution"]), int(r["threadcount"])) for r in rows}:
            if key not in chosen or stamp(env) > chosen[key][1]:
                chosen[key] = (run, stamp(env))
    return {key: run for key, (run, _) in chosen.items()}


def stage_results(runs, chosen, verdicts, out):
    """Write the filtered copy of the runs, returning the rows kept per (solution, threads)."""
    kept = {}
    for n, (run, env) in enumerate(runs):
        header, rows = read_psv(run / "results.psv")
        mine = []
        for r in rows:
            r["solution"] = RENAMED.get(r["solution"], r["solution"])
            key = (r["solution"], int(r["threadcount"]))
            if chosen[key] != run:
                continue
            idx = int(r["idx"])
            passed = r["status"] == "success" and (verdicts is None or verdicts.get((r["solution"], idx)) == "ok")
            if idx > 0 and not passed:
                r.update(dict.fromkeys(TIMINGS, ""))
            mine.append(r)
            kept.setdefault(key, []).append(r)
        if not mine:
            continue
        dest = out / f"{n:02d}-{run.name}"
        dest.mkdir(parents=True)
        shutil.copy2(run / "environment.yaml", dest / "environment.yaml")
        with (dest / "results.psv").open("w") as fh:
            fh.write("|".join(header) + "\n")
            fh.writelines("|".join(r.get(c, "") for c in header) + "\n" for r in mine)
        names = {r["solution"] for r in mine}
        for name, src in solution_dirs(run).items():
            if RENAMED.get(name, name) not in names:
                continue
            shutil.copytree(src, dest / src.name)
            stats = dest / src.name / "stats.yaml"
            stats.write_text(re.sub(r"^solution\s*:.*$", f"solution: {RENAMED.get(name, name)}",
                                    stats.read_text(), count=1, flags=re.M))
    return kept


def ns_to_ms(value):
    return round(int(value) / 1e6, 6) if value else None


def version_of(stats_text):
    m = re.search(r"^engineversion\s*:\s*(.+?)\s*$", stats_text, re.M)
    if not m:
        return None
    raw = m.group(1).strip("'\"")
    inner = re.search(r'version:"([^"]+)"', raw)
    return inner.group(1) if inner else raw


def summarise(runs, chosen, kept, size, verified):
    used = [(run, env) for run, env in runs if run in set(chosen.values())]
    cpus = {cpu_model_of(env) for _, env in runs}
    dates = {str(env["parameters"]["datadate"]) for _, env in runs}
    numa = {numanode_of(env) for _, env in runs}
    if len(cpus) != 1 or len(dates) != 1 or len(numa) != 1:
        raise SystemExit(f"publishData: runs span machines {sorted(cpus)}, data dates {sorted(dates)} and NUMA "
                         f"nodes {sorted(numa)}; publish one machine, data date and NUMA setting at a time")
    newest = max(used, key=lambda pair: stamp(pair[1]))[1]
    system = newest["system"]

    _, meta = read_psv(QUERYMETA)
    queries = [{"idx": int(q["idx"]), "description": q["description"],
                "tags": [t for t in q["tags"].split(",") if t]} for q in meta]

    versions, engines = {}, {}
    for (name, _), run in chosen.items():
        stats = solution_dirs(run)
        src = next((p for n, p in stats.items() if RENAMED.get(n, n) == name), None)
        if src is not None:
            versions.setdefault(name, version_of((src / "stats.yaml").read_text()))
    times, setup = {}, {}
    for (name, threads), rows in sorted(kept.items()):
        engines.setdefault(name, rows[0]["engine"])
        by_idx = {int(r["idx"]): r for r in rows}
        warm = []
        for q in queries:
            r = by_idx.get(q["idx"])
            runs23 = [ns_to_ms(r[c]) for c in TIMINGS[1:]] if r else []
            runs23 = [t for t in runs23 if t is not None]
            warm.append(min(runs23) if runs23 else None)
        times.setdefault(name, {})[str(threads)] = warm
        phases = dict.fromkeys(("load", "sort", "index", "store"))
        for idx, phase in SETUP_PHASES.items():
            r = by_idx.get(idx)
            if r and r["status"] == "success" and ns_to_ms(r["run1timeNS"]) is not None:
                phases[phase] = round((phases[phase] or 0) + ns_to_ms(r["run1timeNS"]), 6)
        setup.setdefault(name, {})[str(threads)] = phases

    order = list(SOLUTIONS) + sorted(set(times) - set(SOLUTIONS))
    solutions = []
    for name in (n for n in order if n in times):
        language, data, note = SOLUTIONS.get(name, ("", "", ""))
        solutions.append({"id": name, "label": name, "engine": engines[name], "version": versions.get(name),
                          "threads": sorted(int(t) for t in times[name]), "language": language,
                          "data": data, "note": note})
    return {
        "updated": str(newest["test date"]),
        "verified": verified,
        "machine": {"cpu": cpus.pop(), "memGB": system.get("memory", {}).get("TotalGB"),
                    "os": " ".join(str(system["os"][k]) for k in ("name", "kernel") if system["os"].get(k))},
        "size": size,
        "datadate": iso(dates.pop()),
        "baseline": BASELINE,
        "solutions": solutions,
        "queries": queries,
        "times": times,
        "setup": setup,
        "history": [],
    }


def build_full(stage, size, python):
    generated = stage / "data.generated.js"
    subprocess.run([python, str(ROOT / "pysrc/convertToJSFormat.py"), str(stage / "results"), str(generated),
                    "--mappings", str(ROOT / "results/mappings.yaml"), "--include-dev-machines"], check=True)
    subprocess.run([python, str(ROOT / "pysrc/buildSite.py"), size, str(stage / "full"), "--data", str(generated)],
                   check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir", type=Path)
    ap.add_argument("stage_dir", type=Path)
    ap.add_argument("--size", required=True)
    gate = ap.add_mutually_exclusive_group(required=True)
    gate.add_argument("--verdicts", type=Path, help="verify.sh output; only verdict ok is published")
    gate.add_argument("--unverified", action="store_true", help="skip the verdict filter (dry run, local preview)")
    a = ap.parse_args()

    verdicts = None if a.unverified else load_verdicts(a.verdicts)
    runs = discover(a.results_dir.resolve())
    chosen = newest_runs(runs)
    if a.stage_dir.exists():
        shutil.rmtree(a.stage_dir)
    (a.stage_dir / "results").mkdir(parents=True)
    kept = stage_results(runs, chosen, verdicts, a.stage_dir / "results")
    summary = summarise(runs, chosen, kept, a.size, verdicts is not None)
    (a.stage_dir / "data.js").write_text("window.PEACHQ_BENCHMARK = "
                                         + json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + ";\n")
    build_full(a.stage_dir, a.size, sys.executable)
    counts = [f"{name}@{threads} {sum(t is not None for t in warm)}/{len(summary['queries'])}"
              for name, by_threads in summary["times"].items() for threads, warm in by_threads.items()]
    print(f"wrote {a.stage_dir}/data.js ({'verified' if verdicts is not None else 'UNVERIFIED'}): " + ", ".join(counts))

if __name__ == "__main__":
    main()
