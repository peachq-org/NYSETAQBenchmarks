# Publishing NYSE TAQ results to peachq.org/benchmark

**Date:** 2026-10-23 · **Status:** stage 1 in review (this PR + the website PR), stage 2 decided, stage 3 deferred

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

- `peachq.org/benchmark` renders KPI tiles, the ratio chart and the per-query table from the
  uploaded `data.js`, and an empty state without it.
- No KX mark or palette colour in the page or the drill-down (asserted by tests in both repos).
- `GO=1 tools/publish.sh` cannot run without a verdicts file.

## Stages

1. **Publish today's numbers.** Fork: `tools/publish.sh`, `pysrc/publishData.py`, the peachq
   theme in `pysrc/buildSite.py`. Website: `/benchmark`. `data.js` reserves an empty `history`.
2. **History and the trend chart.** Owner decisions, verbatim:
   - The trend chart plots "times slower than l" (geometric mean over the 84 queries of peachq's
     cold run-1 time divided by l's), one line for `peachq` and one for `peachq (via DuckDB)`,
     both at 1 thread, against l at 1 thread. The median ratio is shown in the tooltip. A
     DuckDB-relative view may exist as a toggle but l is the headline.
   - l is pinned (20261019) for the series; a deliberate re-pin is a marked break.
   - The x-axis is the DATE THE RUN HAPPENED, never the version: peachq reuses release numbers
     for different builds, so a point is keyed by run date plus an identity of the binary
     (sha256 of the q binary, plus its version string as a label only).
   - A failed or timed-out query counts at 2x the worst ratio posted for that query (the
     benchmark's own rule), so a regression shows as a jump, not a gap.
   - Linear y-axis that starts at zero, with zero drawn as a line; no log scale, no dashed goal
     line.
   - Only verified (correct) results ever enter the history or the chart.
   - Today's laptop run is the first point; expected trajectory from about 52-59x slower than l
     toward 2x.

   The shape is reserved in `data.js`: `history: [{date, solution, version, binarySha256,
   baselineSolution: "l", baselineVersion, threads, size, datadate, ratioGeomean, ratioMedian,
   answered, failed}]`.
3. **AWS spot runner. DEFERRED** (owner: "solve when we get there"). When it comes, the AWS
   machine starts a new series; it never shares a line with the laptop.

## What would unblock each

- Stage 1 → owner review of both PRs, then the correctness-gate PR (verify.sh) merged so a
  verified `GO=1` upload is possible.
- Stage 2 → the runner records the q binary's sha256 per run (environment.yaml or stats.yaml);
  `publishData.py` keeps prior history (read the published `data.js` back, or a history file in
  the fork) and appends one point per verified run; the website page draws the line.
- Stage 3 → the owner deciding to start it; an instance type and a CPU model added to
  `results/mappings.yaml`.
