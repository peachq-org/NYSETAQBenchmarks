# The correctness gate — no published timing without a verified answer

**Date:** 2026-10-23 · **Status:** PR-A built (`feat/correctness-gate`); PR-B and PR-C not started ·
**Rule:** `docs/verification.md`

Written as a file because it is a three-PR programme and PR-B's input (the remaining reds) must survive across
sessions.

## Problem

Nothing establishes that a published timing comes from a correct answer. The only comparator, `src/compareOutput.q`,
needs KDB-X; through the peachq shim (`src/qengine/compareOutput.lite.q`) it took about 2 h for 9 solutions on
`tiny`. Its rules make noise: an absolute 5e-5 float tolerance, order-sensitive comparison where a query's `sortby`
leaves ties, text/blank formatting artefacts, per-engine pivot names. Against DuckDB on `tiny` it agreed for Rayforce
71/84, l 71, peachq 61, Polars Lazy 48 — mostly not bugs. And its reference is one engine: DuckDB 2.0 was wrong twice
in the week it was adopted (NaN poisoning `avg` on idx 20 under IEEE division; `hour/minute/second` on TIMESTAMP_NS
rounding so times printed a second late). Nothing records that a published (solution, engine version) was ever
verified.

## Viability

Probed on the `tiny` outputs (2026-07-01, 10 solutions, 3.6 GB of zstd CSV) before committing to the design:

- Polars reads `.csv.zst` directly and in memory; the largest output (idx 50, 9.1 M rows) loads in 0.6 s. A full
  check of 84 queries × 10 solutions is minutes on one box, with no decompression to disk.
- The measured float spread, after accounting for the q runners' `.Q.f[6]` printing, is at most 6.5e-6 between
  engines that otherwise agree; the base 1e-6 holds everywhere else. Polars' float32 standard deviation (3.3e-5 to
  41% out) is far outside any defensible allowance, so the allowance does not have to hide anything.
- Seven independent implementations run here without KX (DuckDB, chDB, Polars, Pandas, peachq, l, Rayforce), so a
  majority of three is always reachable.

## Constraints

- Clean room: no KX binary, no `pykx`; Python engines from a prepared venv.
- Verification is never inside a timed run.
- `src/compareOutput.q` is upstream's tool for KDB-X users and stays working.
- Disk: goldens are zstd Parquet under the gitignored `DATA/`; outputs are streamed one query at a time.

## Alternatives → chosen

- **DuckDB (or any engine) as the reference** — rejected: the falsifying row. On idx 20 with IEEE division on, DuckDB
  answers NaN and six engines agree on a number; a reference engine marks six correct engines red. Pinned as a test.
- **Port `compareOutput.q` rules to Python unchanged** — rejected: the rules are the noise.
- **A tolerance wide enough to make peachq's six-decimal floats pass** (relative ~1e-3) — rejected: it would admit
  real differences. Chosen instead: the printed rounding of a six-decimal cell is part of its value (5e-7 absolute).
- **Chosen:** one written canonical form (`docs/verification.md`), relative tolerance 1e-6 with a 1e-9 floor plus
  printing slack, a measured per-column float32 allowance (1e-5, `artifacts/verification/float32.psv`), consensus of
  independent implementations (≥3 and more than disagree, else `unresolved`), a tracked ledger
  (`artifacts/verification/ledger.psv`).

## Success measures

- `tiny`, against the consensus (PR-A): DuckDB 83/84 ok, Pandas 84, Polars Eager 73, Polars Lazy 73, Rayforce 83,
  Rayforce Parted 81, chDB 71 + 6 not-written, l 84, peachq 82, peachq (via DuckDB) 82. Pivot names 24–29 green for
  every engine that answers them; the float32 aggregates 41–43, 49, 50, 62, 68, 69 green for every engine whose
  answer is not otherwise wrong; the old order-only noise gone.
- The falsifying row is an automated test (`test/verify/test_verify.py`, `FalsifyingRow`).
- Every remaining red has an owner in PR-B.

## What PR-B does

Adjudicate every remaining red on `tiny`: fix the translation or the runner, or file the engine defect, and pin it.
Input, from PR-A's run (`verdicts.psv`):

| idx | solution | verdict | evidence |
|---|---|---|---|
| 20–23 | chDB (Memory) | value-diff | `avgLiqWMid` NaN where six implementations agree on a number — the same IEEE-division poisoning DuckDB had (divergence 13) |
| 36–43 | Polars (Eager, Lazy) | value-diff | `devSpread` computed in float32: 3.3e-5 out on idx 36, 41% on idx 41 |
| 46 | Polars (Eager, Lazy) | value-diff | `weightedOfferPrice` −71.23 vs 30.26 on one sym |
| 47–48 | Polars (Eager, Lazy) | value-diff | rolling `price` null at row 0 where the consensus has 1.9913 (idx 47): the first 19 rows of a 20-trade window |
| 49–50 | chDB (Memory) | value-diff | `movingLiqWMid` null at row 3 where the consensus has 31.990588 |
| 49–50 | peachq, peachq (via DuckDB) | value-diff | `movingLiqWMid` 84.518333 vs 84.530332 (l, on the same `kdb.psv`, agrees with the consensus) |
| 52 | chDB (Memory) | value-diff | cumulative `size` 1081106.24 vs 1081066.1 |
| 53, 55 | Rayforce Parted | value-diff | cumulative `size` 5064 vs 100 at row 0 (idx 53), 395187 vs 35 (idx 55); grouped Rayforce is ok |
| 54 | DuckDB (Index) | value-diff | `movingvwap` 20.191211 vs 20.190931 (1.4e-5): float32 window sums or a frame difference — measure before any allowance |
| 61 | Rayforce, Rayforce Parted | missing | engine error |
| 24–29 | chDB (Memory) | not-written | no chDB pivot queries; writing them is optional |

Then run every size the dashboard publishes, and add `float32.psv` rows only with a measurement.

## What PR-C does

The dashboard (`convertToJSFormat.py` → `index.html`) marks a (solution, engine version) with no ledger row for its
query file, parameters and date as unverified, and shows its fail count where there is one; the converter warns when
it is asked to publish a version never verified. Neither changes what is measured.
