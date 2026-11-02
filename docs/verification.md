# Verifying query outputs

A published timing means something only if the answer it timed was correct. This file is the rule
[`benchmarks/inmemory/verify.sh`](../benchmarks/inmemory/verify.sh) (`pysrc/verify/`) implements, written down once;
the code implements exactly this and nothing else. Changing the rule means changing this file in the same PR.

## 1. The canonical form

Every `queryoutput_<idx>.csv` (or `.csv.zst`, decompressed in memory) is read as text and reduced to one canonical
table before anything is compared.

**Cells.** Each cell is trimmed of surrounding whitespace, then:

| Written as | Canonical value |
|---|---|
| empty, `" "`, `0n`, `-0n`, `0N`, `0N` + one letter (`0Nj`, `0Ne`, …), `nan`, `-nan`, `NaN`, `null` (any case) | null — all one null |
| `0w` / `-0w`, `inf` / `-inf`, `infinity` | ±infinity |
| `true` / `false`, `1b` / `0b` | the integer 1 / 0 |
| a time: q `0D09:32:06.999999533`, `09:32:06.999999533`, DuckDB `09:32:06`, Polars `09:32:06.000000000`, q minute `09:32` | integer nanoseconds since midnight |

A NaN is null. That is deliberate: q has no NaN distinct from its float null, and an engine whose `avg` answers NaN
where the others answer a number is wrong whichever way it spells it.

**Columns.** Each column of each file takes the narrowest kind every non-null cell admits, tried in this order:
integer (`-?\d+`); integer with booleans; float (decimal or exponent notation, or infinity); time; else text. A
column with no non-null cell is null-only and matches any kind. So integers are widened (an `int32` and an `int64`
compare equal), times written as integer nanoseconds (Rayforce) equal times written as text, and booleans written
`true` equal booleans written `1`. When two files disagree on a column's kind, integer and float read as float;
text against a number is a `value-diff`.

**Names and order.** Column names are compared exactly (case included); column order is ignored. Rows are sorted on
every column, non-float columns first in column-name order, then float columns — except for queries tagged `sort` in
[`querymeta.psv`](../artifacts/queries/inmemory/querymeta.psv), whose emitted order is part of the answer and is kept
(section 3).

## 2. Floats

Two float cells `a` and `b` agree when both are null, or they are equal, or

    |a - b| <= max(rtol * max(|a|, |b|), 1e-9) + slack(a) + slack(b)

- **`rtol` is 1e-6.** Relative, so a sum of 4.6e9 and a spread of 0.01 are held to the same number of digits;
  upstream's absolute 5e-5 demands fourteen significant digits of the first and accepts a 0.5% error in the second. The 1e-9 floor stops a value
  that should be zero from failing on rounding noise.
- **`slack` is how the cell was printed.** A cell in fixed notation with six or more decimals carries half a unit in
  its last place (`0.120348` carries 5e-7). Both q runners write floats with `.Q.f[6]`
  (`src/runQueries.q` `persistOutput`, and the lite runner after it), so a q answer of `0.001235` stands for anything
  in [0.0012345, 0.0012355]; read as exact, every q output below about 0.5 would fail a relative test. Shorter and
  exponent forms carry no slack: they are what shortest-round-trip printers (DuckDB, Polars, Pandas, chDB) write, and
  `26.64` from one of those means exactly the double nearest 26.64.
- **The float32 allowance.** This fork stores TAQ prices and sizes as float64 (`FORK.md` divergence 31), where KX's
  upstream stores them as `real`s (float32). An engine that keeps an intermediate result in float32 can still differ
  from the double engines in the last digits; where that is measured, and only there, a column is compared at a looser
  `rtol`, listed with its evidence in [`artifacts/verification/float32.psv`](../artifacts/verification/float32.psv)
  (`idx|column|rtol|evidence`). The table is empty: its three rows (idx 41–42 `avgWeightedSpread`, DuckDB's
  `ask - bid` in REAL, 6.5e-6; idx 62 `size`, Polars Lazy's sum of a REAL, 1.1e-6) were measured on float32 data and
  retired when the data became float64, and `tiny` (2026-07-01) and the fixture (2026-04-01) verify without them. A
  row is added only with a measurement, at no more than **1e-5**; a rise above that is a defect to explain, not an
  allowance to widen. It does not cover a different answer: Polars' `dev` of the spread was 3.3e-5 out on idx 36 and
  41% out on idx 41 because it was the sample deviation, and the fix was the translation (`FORK.md` divergence 26),
  not an allowance.

Rows that tie on every non-float column are sorted by their floats, and two engines' floats can order such a tie
differently while agreeing within tolerance. Where the sorted tables differ only inside such ties, the tied rows are
paired one to one, greedily, on their float columns; the outputs agree if every row finds a partner.

## 3. Queries whose order is the answer

For a `sort`-tagged query the candidate's emitted order is compared with the golden's. Rows of the golden that tie
on the query's `sortby` keys (`querymeta.psv`, up to and including the first float key) may come in any order: a
float key is known only within tolerance, so neither is the order a later key gives inside it. idx 14–15 sort on
`mid` (descending) then `time`, so the order inside a tie on `mid`, as each engine rounds it, is not part of the
answer.

If the emitted order differs beyond that but the sorted tables agree, the verdict is `order-only`; this is the only
query class where `order-only` can occur.

**Order inside a running computation.** A moving or cumulative value (`mavg`, `sums`, a window frame; idx 47–55)
depends on the order of the rows it runs over, whether or not the query is `sort`-tagged. That order is the table's:
`time`, ties kept in load order, which is what `xasc` on the q side and `rowid` on the SQL side give. A translation
states it explicitly (`ORDER BY rowid`, not `ORDER BY time`, whose ties any engine may break as it likes). A solution
whose layout keeps another physical order (`sym,time` for Rayforce Parted, and for KDB-X (Parted) running the same
`kdb.psv`) answers a different question on the
cumulative queries that span instruments (idx 53, 55); it stays red, and the reason is recorded in `FORK.md`.

## 4. The consensus golden

There is no reference engine. A query's golden is the canonical answer a majority of **independent
implementations** share:

- Solutions of one engine are one implementation and one vote: DuckDB; chDB; Polars (Eager and Lazy); Pandas; peachq
  (in memory and via DuckDB, both the same q evaluator); l; Rayforce (grouped and parted); KDB-X (every KDB-X
  solution, KDB-X SQL and pykx). The table is `SOLUTIONS` in `pysrc/verify/solutions.py`; an unknown solution is its
  own implementation.
- An implementation backs every answer one of its solutions gave.
- The golden is the answer backed by **at least three implementations and by more implementations than answered
  anything else**. Otherwise the query is `unresolved` for every solution — never guessed, and never decided by
  picking an engine.
- The golden is stored as zstd Parquet under `DATA/verification/<size>_<datadate>_<paramhash>/` (gitignored), from
  the most precisely printed agreeing solution, with a `manifest.psv` naming which solutions agreed. A run whose own
  panel has no majority for a query (say, one new engine version on its own) is checked against the stored golden.

## 5. Verdicts

| Verdict | Meaning |
|---|---|
| `ok` | Agrees with the golden |
| `order-only` | Same rows, different order, on a `sort`-tagged query |
| `value-diff` | Same shape, a cell differs; the evidence names the first |
| `shape-diff` | Different column names or row count, or the file cannot be read |
| `missing` | The query exists for this solution but it wrote no output (error, timeout); the evidence is its `results.psv` status |
| `not-written` | The solution's query file has no query at this idx (or `results.psv` says `emptyquery`) |
| `unresolved` | No majority (section 4) |

A solution passes a query on `ok`. `not-written` is reported, not failed. Everything else fails.

## 6. What a run writes

Into `--report` (default `<first -r dir>/verification/`):

- **`verdicts.tsv`** — machine-readable, read by the peachq.org publish script: tab-separated, header line
  `solution	idx	verdict`, one row per (solution, query idx). `solution` is the solution name exactly as in `results.psv`
  and `stats.yaml` (`DuckDB (Index)`, `peachq (via DuckDB)`, `Rayforce Parted`), taken from the `solution:` line of
  the run's `<dir>/stats.yaml`; `verdict` is one of the seven above.
- **`verdicts.psv`** — the same rows with an `evidence` column, for people.

And one row per solution into [`artifacts/verification/ledger.psv`](../artifacts/verification/ledger.psv), replacing an
earlier row with the same key: `verified|solution|implementation|engineversion|queryfile|queryhash|paramhash|datadate|size|ok|fail|unresolved|notwritten|queries|commit`.
The key is what makes a verification stale — solution, `engineversion` (from its `stats.yaml`), the SHA-256 of its
query file and of the parameter directory, the data date and the size. A published (solution, engine version) pair
with no `ledger.psv` row for its query file and parameters has not been verified.

The ledger is tracked, under `artifacts/`, because `results/` is gitignored and the ledger is the one output of a run
that must outlive it: it is the record a reader, and later the dashboard, checks a published number against.
