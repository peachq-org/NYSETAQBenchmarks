# openq — the oracle harness

Runs the 84 in-memory benchmark queries under [openq](https://github.com/timestored/openq)'s
`./q` and under DuckDB, and diffs the two.

## The standing rule: DuckDB is the oracle, kdb+ is never used

`artifacts/queries/inmemory/kdb.psv` and `duckdb.psv` are row-aligned by `idx`, and this
repo asserts (CLAUDE.md, "Engine equivalence is a hard requirement") that every engine
returns identical output for a given `idx`, floats within `5e-5`. So **DuckDB executing the
SQL sibling is a clean-room oracle for the q result.** Nothing here runs, decompiles or
consults a kdb+ / KDB-X binary, and nothing here should ever start to.

`src/compareOutput.q` is the reference for the comparison, but it needs KDB-X ≥ 5.0 to run,
so `compare.py` ports its logic instead.

## The parameters must come from the data

`artifacts/parameters/test/` names instruments (`ZKPU`, `ZOOZ.W`, `kfmo`, …) that do **not
appear** in `external/kx/taq/testdata/`. Used as-is, every parameterised query returns
nothing and the comparison proves nothing. `genparams.q` therefore derives the parameters
from the loaded data with the recipe in `artifacts/parameters/genParameters.q` — most-traded
instrument, least-traded, and sets of each — plus one absent symbol per set so the
no-such-instrument arm still gets exercised. Always sanity-check that a parameterised query
returns a non-empty result on both engines before trusting a match.

## Running it

```bash
export TAQ_ROOT=$PWD TAQ_PARAMS=$PWD/openq/params
export OPENQ=/path/to/openq            # the openq checkout holding ./q

OPENQ_DIR=$PWD/openq $OPENQ/q openq/genparams.q
OPENQ_DIR=$PWD/openq TAQ_OUT=$PWD/openq/out-q $OPENQ/q openq/runq.q
python3 openq/rundb.py --root "$TAQ_ROOT" --params "$TAQ_PARAMS" \
    --out openq/out-duck --db openq/taq.duckdb
python3 openq/compare.py --meta artifacts/queries/inmemory/querymeta.psv \
    --a openq/out-q --b openq/out-duck
```

`ASAN_OPTIONS=detect_leaks=0` is wanted for an openq debug build. `--data DIR` points
`rundb.py` at a different PSV directory (used to regenerate the trimmed slice openq vendors
into its own test suite). `duckdb` is found on `PATH` or via `DUCKDB_BIN`.

| file | role |
|---|---|
| `taq.q` | loads `trade` / `quote` / `exnames` from the PSVs, schema per `external/kx/taq/taq/inputSchema.q`, row order per the canonical `-sortcols time` |
| `genparams.q` | derives the instrument parameters from the data |
| `runq.q` | runs `kdb.psv` under openq: 3 runs per query, last result to `queryoutput_<idx>.csv`, timings to `timings.psv` |
| `rundb.py` | the same for `duckdb.psv` under the DuckDB CLI |
| `compare.py` | the comparator |

## Output format

Both runners write one `queryoutput_<idx>.csv` per query, in the shape
`src/runQueries.q`'s `persistOutput` and the DuckDB executor's `write_csv` already agree on:
floats at 6dp, timestamps as q timespan literals, booleans as `0`/`1`. `compare.py`
canonicalises further — the several null spellings to one null, temporal literals to one
form — because it cannot lean on a q type dictionary the way `compareOutput.q` does.

Verdicts are `match`, `order-only` (same rows, different order), `mismatch`, `missing-a` /
`missing-b` (an engine produced nothing) and `not-comparable` (`--skip`).

## Timings

`timings.psv` carries `idx|status|run2timeNS|run3timeNS`, the two warm runs, following the
upstream protocol of comparing warm runs at equal thread count. They are a **benchmark-repo
artifact only** and are deliberately not carried into openq's test suite.

## Known not-comparable rows

`idx` 24–29 have **no working oracle**: `duckdb.psv` ends each with `GROUP BY time`, but the
CTE it pivots aliases the bucket as `minute`, so DuckDB answers `Binder Error: Referenced
column "time" not found in FROM clause`. On the q side `src/pivot.q` does not load under
openq either, so neither half of the pair runs.
