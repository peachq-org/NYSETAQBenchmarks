#!/usr/bin/env python3
"""Stage benchmark results for peachq.org/benchmark.

    python pysrc/publishData.py RESULTS_DIR STAGE_DIR --size SIZE (--verdicts FILE | --unverified)
                                [--page-solutions "A,B,..."] [--history FILE]

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
  data.js   the summary the native page reads (schema below), for the page's
            curated solutions only (--page-solutions, default PAGE_SOLUTIONS).
  full/     the drill-down: pysrc/convertToJSFormat.py over results/, then
            pysrc/buildSite.py. It keeps every solution.

A verified publish also appends to the speed history (--history, default
artifacts/publish/history.psv), one row per (run date, solution, thread count)
not already recorded; an unverified one leaves it alone.

Speed is MPH with the target, DuckDB (Index), as 100. At one thread count, for
each query the target answered: ratio = solution's warm time / the target's. A
query the solution has no time for counts at 2x the worst ratio any page
solution posted for it (the target's own 1 included); a query no page solution
but the target answered is skipped. MPH = 100 / geomean(ratios), and the median
MPH is 100 / median(ratios).

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
      target:    the solution that is 100 MPH, today the baseline
      baselineVersion: the target's engine version, e.g. "2.0.0"
      solutions: [{id, label, engine, version, threads: [1, 4], language, data, note}]
      queries:   [{idx, description, tags: [..]}], in idx order
      times:     {<solution id>: {<threads>: [warm ms or null, one per entry of queries]}}
      setup:     {<solution id>: {<threads>: {load, sort, index, store}}}, ms or null
      mph:       {<solution id>: {<threads>: {mph, mphMedian, answered, failed, total}}}
      history:   every row of the history file, oldest first:
                 [{date, solution, version, binarySha256, target, baselineVersion,
                   threads, size, datadate, mph, mphMedian, answered, failed}]
    }

answered counts the queries with a verified time, of total; failed counts the
ones charged the penalty. A history series is one (solution, threads, target,
baselineVersion, size): a new target version starts a new series, never joined
to the old one.

A solution id is its results.psv name, so verdicts, the drill-down and the
page all key on one string. Warm ms is min(run2, run3). Setup times are run 1
of the load rows: load is idx 0 plus idx -1 (transform), sort -2, index -3,
store -4. Every run must come from one machine, one data date and one NUMA
setting; a mixed tree is refused rather than averaged. A history row is keyed by
the date the run happened plus the binary's sha256 (stats.yaml binarysha256, which
queryEngines.sh records for the q binaries it runs; empty when unrecorded), never
by version: peachq reuses release numbers for different builds.
"""
import argparse
import csv
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

import yaml

from convertToJSFormat import cpu_model_of, numanode_of, parse_stats, solution_stats_dirs

ROOT = Path(__file__).resolve().parent.parent
QUERYMETA = ROOT / "artifacts" / "queries" / "inmemory" / "querymeta.psv"
BASELINE = "DuckDB (Index)"
HISTORY = ROOT / "artifacts" / "publish" / "history.psv"
HISTORY_FIELDS = ("date", "solution", "version", "binarySha256", "target", "baselineVersion", "threads", "size",
                  "datadate", "mph", "mphMedian", "answered", "failed")
HISTORY_KEY = ("date", "solution", "threads", "binarySha256", "target", "baselineVersion", "size")
PAGE_SOLUTIONS = ("peachq", "peachq (via DuckDB)", "DuckDB (Index)", "l", "Rayforce", "Rayforce Parted",
                  "Polars (Lazy)", "Pandas")
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
        for name, src in solution_stats_dirs(run).items():
            if RENAMED.get(name, name) not in names:
                continue
            shutil.copytree(src, dest / src.name)
            stats = dest / src.name / "stats.yaml"
            stats.write_text(re.sub(r"^solution\s*:.*$", f"solution: {RENAMED.get(name, name)}",
                                    stats.read_text(), count=1, flags=re.M))
    return kept


def ns_to_ms(value):
    return round(int(value) / 1e6, 6) if value else None


def version_of(stats_path):
    """engineversion from stats.yaml, with Rayforce's {version:"x" ...} record reduced to x."""
    raw = parse_stats(stats_path)[1]
    inner = re.search(r'version:"([^"]+)"', raw or "")
    return inner.group(1) if inner else raw


def binary_sha256_of(stats_path):
    found = re.search(r"^binarysha256\s*:\s*'?([0-9a-f]{64})'?\s*$", stats_path.read_text(), re.M)
    return found.group(1) if found else ""


def speeds(times, target):
    """{solution: {mph, mphMedian, answered, failed, total}} for one thread count's {solution: warm times}."""
    ratios = {name: [] for name in times}
    failed = dict.fromkeys(times, 0)
    for i, base in enumerate(times[target]):
        if not base:
            continue
        posted = {name: max(t[i], 1e-6) / base for name, t in times.items() if t[i] is not None}
        if len(posted) < 2:
            continue
        worst = max(posted.values())
        for name in times:
            ratios[name].append(posted.get(name, 2 * worst))
            failed[name] += name not in posted
    return {name: {"mph": round(100 / math.exp(sum(map(math.log, rs)) / len(rs)), 3),
                   "mphMedian": round(100 / statistics.median(rs), 3),
                   "answered": sum(t is not None for t in times[name]), "failed": failed[name],
                   "total": len(times[name])}
            for name, rs in ratios.items() if rs}


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
        stats = solution_stats_dirs(run)
        src = next((p for n, p in stats.items() if RENAMED.get(n, n) == name), None)
        if src is not None:
            versions.setdefault(name, version_of(src / "stats.yaml"))
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


def curate(summary, page):
    """Narrow the summary to the page's solutions and add their speeds."""
    if BASELINE not in page or BASELINE not in summary["times"]:
        raise SystemExit(f"publishData: the target {BASELINE} must be on the page and in the runs")
    times = {name: by_threads for name, by_threads in summary["times"].items() if name in page}
    mph = {}
    for threads in summary["times"][BASELINE]:
        shown = {name: by_threads[threads] for name, by_threads in times.items() if threads in by_threads}
        for name, speed in speeds(shown, BASELINE).items():
            mph.setdefault(name, {})[threads] = speed
    summary.update(solutions=[s for s in summary["solutions"] if s["id"] in page], times=times,
                   setup={name: v for name, v in summary["setup"].items() if name in page}, mph=mph,
                   target=BASELINE,
                   baselineVersion=next(s["version"] for s in summary["solutions"] if s["id"] == BASELINE))


def history_rows(summary, chosen, envs):
    """One row per (solution, threads), each version read from the run that measured that thread count."""
    def stats_of(name, threads):
        run = chosen[(name, int(threads))]
        return run, next((p / "stats.yaml" for n, p in solution_stats_dirs(run).items() if RENAMED.get(n, n) == name),
                         None)

    rows = []
    for name, by_threads in summary["mph"].items():
        if name == BASELINE:
            continue
        for threads, speed in by_threads.items():
            run, stats = stats_of(name, threads)
            target = stats_of(BASELINE, threads)[1]
            rows.append({"date": str(envs[run]["test date"]), "solution": name,
                         "version": (version_of(stats) if stats else None) or "",
                         "binarySha256": binary_sha256_of(stats) if stats else "",
                         "target": summary["target"], "baselineVersion": (version_of(target) if target else None) or "",
                         "threads": int(threads), "size": summary["size"], "datadate": summary["datadate"],
                         "mph": speed["mph"], "mphMedian": speed["mphMedian"], "answered": speed["answered"],
                         "failed": speed["failed"]})
    return rows


def read_history(path):
    if not path.is_file():
        return []
    _, rows = read_psv(path)
    for r in rows:
        r.update({k: int(r[k]) for k in ("threads", "answered", "failed")},
                 **{k: float(r[k]) for k in ("mph", "mphMedian")})
    return rows


def record_history(path, new_rows):
    """Append the rows whose key is not yet in the file; return the whole history."""
    rows = read_history(path)
    seen = {tuple(str(r[k]) for k in HISTORY_KEY) for r in rows}
    for r in new_rows:
        key = tuple(str(r[k]) for k in HISTORY_KEY)
        if key not in seen:
            seen.add(key)
            rows.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        fh.write("|".join(HISTORY_FIELDS) + "\n")
        fh.writelines("|".join(str(r[k]) for k in HISTORY_FIELDS) + "\n" for r in rows)
    return rows


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
    ap.add_argument("--page-solutions", default=",".join(PAGE_SOLUTIONS),
                    help="comma-separated solutions data.js carries; full/ keeps every one (default: %(default)s)")
    ap.add_argument("--history", type=Path, default=HISTORY, help="the speed history (default: %(default)s)")
    a = ap.parse_args()

    verdicts = None if a.unverified else load_verdicts(a.verdicts)
    runs = discover(a.results_dir.resolve())
    chosen = newest_runs(runs)
    if a.stage_dir.exists():
        shutil.rmtree(a.stage_dir)
    (a.stage_dir / "results").mkdir(parents=True)
    kept = stage_results(runs, chosen, verdicts, a.stage_dir / "results")
    summary = summarise(runs, chosen, kept, a.size, verdicts is not None)
    curate(summary, {name.strip() for name in a.page_solutions.split(",") if name.strip()})
    if verdicts is not None:
        summary["history"] = record_history(a.history, history_rows(summary, chosen, dict(runs)))
    else:
        summary["history"] = read_history(a.history)
    (a.stage_dir / "data.js").write_text("window.PEACHQ_BENCHMARK = "
                                         + json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + ";\n")
    build_full(a.stage_dir, a.size, sys.executable)
    counts = [f"{name}@{threads} {sum(t is not None for t in warm)}/{len(summary['queries'])}"
              for name, by_threads in summary["times"].items() for threads, warm in by_threads.items()]
    print(f"wrote {a.stage_dir}/data.js ({'verified' if verdicts is not None else 'UNVERIFIED'}): " + ", ".join(counts))
    print(f"{'solution':<22}threads      MPH  median MPH  answered  ({summary['target']} "
          f"{summary['baselineVersion']} = 100 MPH)")
    for name, by_threads in summary["mph"].items():
        for threads, v in sorted(by_threads.items(), key=lambda kv: int(kv[0])):
            print(f"{name:<22}{threads:>7}{v['mph']:>9.1f}{v['mphMedian']:>12.1f}  {v['answered']:>4}/{v['total']}")

if __name__ == "__main__":
    main()
