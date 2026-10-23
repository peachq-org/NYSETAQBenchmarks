# Publishing NYSE TAQ results to peachq.org/benchmark

**Date:** 2026-10-23 · **Status:** stage 1 merged, stage 2 in review (the MPH PRs in the fork and the website), stage 3 deferred

Written as a file rather than a PR body because it is a three-stage programme and the stage 2
decisions must survive across sessions.

## Problem

The fork's results exist only as PSVs and as a dashboard nobody hosts. peachq needs a public,
honest answer to "how fast is it on this benchmark, and is it getting faster", without borrowing
KX's branding and without ever publishing a timing for a wrong answer.

## Viability

Probed on today's tiny run (laptop, i7-12700H, data date 20260701), all nine run directories
through `pysrc/publishData.py --unverified`:

| solution @ 1 thread | queries answered (status success) | geometric mean of run-1 time / l's |
|---|---|---|
| peachq | 84 / 84 | 58.9x |
| peachq (via DuckDB) | 83 / 84 (idx 60 timed out) | 53.1x over the 83; 57.7x with the timeout at 2x the worst ratio |

That is the owner's 52-59x starting figure, so the data already carries what stage 2 plots.

## Constraints

- Clean room: no KX product is downloaded or run anywhere in the pipeline.
- No KX branding on peachq.org: one credit line only (KX's NYSE TAQ benchmark, Apache-2.0,
  github.com/KxSystems/NYSETAQBenchmarks), run by the peachq-org fork.
- The numbers are not in the website repo: they are uploaded to `/data/benchmark/`, which
  deploys never touch.
- Only verified results are published: a (solution, query) whose verify.sh verdict is not `ok`
  is shown as absent.
- Laptop results name the machine and say they are not comparable with KX's server results.

## Alternatives → chosen

- Host the upstream dashboard alone, re-skinned → rejected as the front page: it is a tool for
  slicing, not a summary, and it carries KX's design. Kept as the drill-down.
- Commit the numbers into the website repo → rejected: every run would be a website PR, and
  deploys would overwrite uploaded data.
- **Chosen:** a native peachq page (`static/benchmark.php`) reading an uploaded `data.js`, with a
  "Full results" link to the fork's re-themed dashboard under `/data/benchmark/full/`.

## Success measures

- `peachq.org/benchmark` renders the MPH tiles, speedometer, trend chart, MPH bars and the
  per-query table from the uploaded `data.js`, and an empty state without it.
- No KX mark or palette colour in the page or the drill-down (asserted by tests in both repos).
- `GO=1 tools/publish.sh` cannot run without a verdicts file.

## Stages

1. **Publish today's numbers.** Fork: `tools/publish.sh`, `pysrc/publishData.py`, the peachq
   theme in `pysrc/buildSite.py`. Website: `/benchmark`. `data.js` reserves an empty `history`.
2. **Speed in MPH, history and the trend chart.** Owner rulings of 2026-10-23, which replace
   the earlier "times slower than l" rulings:
   - Speed is MPH, with DuckDB (Index) as 100. For a solution at a thread count, each query
     DuckDB answered and verified gives ratio = the solution's warm time (min of runs 2 and 3) /
     DuckDB's at the same thread count. A query the solution failed, timed out or did not verify
     counts at 2x the worst ratio any shown solution posted for it (the benchmark's own rule); a
     query no shown solution but DuckDB answered is skipped. MPH = 100 / geomean(ratios); the
     median MPH (100 / median) and answered/total are reported with it. DuckDB's version is named:
     "DuckDB 2.0.0 = 100 MPH". Linear everywhere, no log scales.
   - The trend chart plots MPH over the DATE THE RUN HAPPENED, never the version (peachq reuses
     release numbers), one line each for `peachq` and `peachq (via DuckDB)`, on a linear y-axis
     from 0 with the zero line drawn and no goal line. A point's tooltip shows run date, version
     label, MPH, median MPH and answered/84. One point renders as a labelled dot.
   - History records MPH: `artifacts/publish/history.psv`, appended on every verified publish,
     one row per (run date, solution, thread count) with the version label, the binary's sha256
     (empty when the runner did not record it, never invented), the target and its version,
     size, data date, MPH, median MPH, answered and failed. Publishing the same run twice adds no
     row. A new DuckDB version or target starts a new, labelled series that the chart never joins
     to the old. If peachq ever passes DuckDB the target becomes `l`, as a new series (not built;
     the target is a field so it can change).
   - The page shows a curated set (peachq, peachq (via DuckDB), DuckDB (Index), l, Rayforce,
     Rayforce Parted, Polars (Lazy), Pandas), chosen at publish time; Full results shows every
     verified solution.
   - Only verified (correct) results ever enter the history or the chart.
   - Today's laptop run is the first point: peachq 25.0 MPH, peachq (via DuckDB) 29.9 MPH at one
     thread.

   Rules settled:
   - Speed is MPH, with DuckDB as 100.
   - History records MPH per run.
   - The page shows a curated set; Full results shows everything.
3. **AWS spot runner. DEFERRED** (owner: "solve when we get there"). When it comes, the AWS
   machine starts a new series; it never shares a line with the laptop.

## What would unblock each

- Stage 1 → owner review of both PRs, then the correctness-gate PR (verify.sh) merged so a
  verified `GO=1` upload is possible.
- Stage 2 → owner sign-off of the local preview, then both PRs merged (fork first) and a
  verified `GO=1` publish.
- Stage 3 → the owner deciding to start it; an instance type and a CPU model added to
  `results/mappings.yaml`.
