# FORK.md

This repository is a community fork of
[KxSystems/NYSETAQBenchmarks](https://github.com/KxSystems/NYSETAQBenchmarks), forked at
`a316c8b`. Upstream remains the origin of the benchmark's design and of the dashboard at
benchmark.kx.com.

`main` is the fork line; upstream is merged in periodically via the `upstream` remote.
Every divergence is listed below with whether it is offerable back to KX.

## Why this fork exists

The upstream suite has one documented path for outside engines ("add a Python executor
class") and one external vendor PR in its history. This fork makes the same suite a venue
any engine can enter on equal terms, against a written contract, while staying close enough
to upstream that results remain comparable.

No vendor is privileged here, including peachq.

## Divergences from upstream

| # | Divergence | Why | Offerable upstream? |
|---|---|---|---|
| 1 | taq submodule at `dcfc9c6`, not `ecf6daa` | The recorded pin breaks the smoke test, the QuickStart and three of six SIZEs | Yes, offered (see ledger) |
| 2 | `duckdb.psv` idx 24–29 `GROUP BY minute` | The queries never bound; six of 84 have no DuckDB answer in published results | Yes, offered (see ledger) |
| 3 | DuckDB pinned exactly | `duckdb>=1.4` makes published numbers irreproducible | Yes, offered (see ledger) |
| 4 | README `add_solution_name` + test-data path | Stale references | Yes, offered (see ledger) |
| 5 | PR #14 (rayforce adapter) merged | Upstream PR still open; the fork does not gate vendors on KX's review queue | N/A, it is upstream's own PR |
| 6 | `duckdb_con.py` inlines parameters for `pivot`-tagged queries | DuckDB rejects bound parameters in a data-driven `PIVOT` source; without this, divergence 2 fixes nothing observable | Yes, folded into the same offer (see ledger) |
| 7 | `qlite` engine arm, `QBIN`-selected | Lets any q implementation run the benchmark; upstream has no path for one | Yes, in principle |
| 8 | `src/runQueries.q` version guard relaxed to a capability check | `5.0>.z.K` rejects every non-KDB-X q, including ones that can run the corpus | Yes, standalone |
| 9 | Capability shim for `.log.*` / `.mem.objsize` — landed as `src/qengine/runQueries.lite.q`, not as a shim | Both come from KDB-X modules unavailable to other implementations. A shim turned out not to be enough: `src/runQueries.q` uses KDB-X typed lambda parameters and progressive blocks inside a conditional, which a second implementation cannot **parse**, so no amount of predefining names helps. See "Follow-ups" | No — it is a fork-owned file, meant to be deleted |
| 10 | `runQueries.lite.q` renders an unmeasured cell as the empty string rather than through `string` | peachq's `string 0Nj` is `"0Nl"` where kdb+'s is `""`, so every qlite `results.psv` carried `0Nl` in the null timing and IO columns and `convertToJSFormat.py` died parsing it | No — a fork-owned file, working around a second implementation's formatting |
| 11 | `results/mappings.yaml` names development machines and `convertToJSFormat.py` drops their runs unless `--include-dev-machines` is passed | The only host this fork has is a laptop. Without a mapping entry no dashboard data can be generated at all; with a bare one, laptop timings can land on the same chart as an EPYC's | Yes, in principle — see below |
| 12 | `DATAFORMAT=splayed` and `src/qengine/psvToSplayed.q`, a plain-q PSV→splayed kdb converter | `src/taqToKDB.q` needs the KDB-X module system and typed lambda parameters, so no other q implementation can build a kdb database. Without one, the `qlite` arm's `idx 0` row measured PSV parsing and was not comparable with the kdb+ arms' | Yes, in principle — it gives upstream a kdb data path with no KDB-X in it |
| 13 | DuckDB pinned to 2.0.0 with `ieee_floating_point_ops` and `error_on_division_by_zero` off | 2.0 made `x/0` IEEE, and the NaN poisons `avg`: idx 20 answered `-nan` where q, Polars and Pandas agree on a value. The twins were validated on 1.x semantics | Yes, as a bug fix once upstream moves to 2.0 |
| 14 | The splayed loader converts enum columns to symbols | Mirrors upstream `73dace3` in `loadKDBDBIntoMemory`; the fork's loader predated it | N/A, follows upstream |
| 15 | `l` engine arm (`LBIN`) on the qlite runner and database; `PYRUN` launches the Python arms | `l` (lv1.sh) is a second non-KX q. `PYRUN` lets a host skip `pykx`, whose wheel bundles a KX q that this fork never downloads | `PYRUN` yes; `l` in principle, as for qlite |
| 16 | Rayforce's database builds without KDB-X (`exportRayCSV.q -format splayed`, via the qlite binary); `runRayforce.sh` emits the 18-column contract and takes `-statsDir` | The export needed a kdb+ database and a KDB-X binary; the extra `sortcols`/`engineversion` result columns misaligned merged results after upstream moved them into stats.yaml | Yes, as feedback on PR #14 |
| 17 | `compareOutput.lite.q` supplies `kx.log`; `compareOutput.q` reads the header with upstream's `head -n 1` and trims text columns | Lets any q run the comparator; the byte-range `read0` behaves differently across implementations; q writes a blank char as `" "`, the Python engines as `""` | The trim and header read, yes |
| 18 | `peachq (via DuckDB)` solution: `runQueries.lite.q -store duckdb` writes trade and quote into an in-memory DuckDB through peachq's `:pq:duckdb:` handle and rebinds the names to the linked tables (setup row -4) | Measures the same unchanged `kdb.psv` qSQL with peachq's pushdown into DuckDB, against DuckDB's own SQL twins on the same box | No, peachq-specific |
| 19 | The lite runner reports a run 1 past max(30 s, 5x the median run 1) as `timeout` and skips its runs 2-3 | A query cannot be interrupted in-process (SIGINT ends a script, `\T` is for client queries), so one pathological query cost three runs | Yes, in principle; upstream has no per-query cap |
| 20 | The splayed loader turns `exnames` into a char!symbol map | `src/runQueries.q` does (`exec ex!`$name from exnames`); left string-valued, `by sym, exnames ex` grouped on strings, which was 53 s / 7 min 49 s a run on peachq (idx 41/42) | N/A, follows upstream |
| 21 | `tools/publish.sh` + `pysrc/publishData.py`: stage results for peachq.org/benchmark (a summary `data.js` and the drill-down below) and upload them to `/data/benchmark/`; only `ok` verdicts from verify.sh are published, and `GO=1` refuses without a verdicts file | The fork's results need a home that is not benchmark.kx.com; publishing an unverified timing would rank a wrong answer | No |
| 22 | `pysrc/buildSite.py` re-themes the drill-down to peachq.org's tokens and font stacks, drops the remaining kx.com link and the consent-manager handler, and asserts no KX mark or palette colour survives in the built copy | A fork-hosted copy must not look like a KX property | No |
| 23 | `CNAME` (`benchmark.kx.com`) removed | It names KX's domain; this fork does not publish through GitHub Pages | No |
| 24 | `duckdb.psv` idx 24–29 name pivot columns by the pivot value alone (`USING AVG(liqWMid)`, no `AS avgLiqWMid`) | DuckDB answered `H_avgLiqWMid` where every other engine answers `H`, so six queries could never match. A translation that names columns differently is fixed in the translation, not taught to the comparator | Yes, standalone |
| 25 | Output verification by consensus: `benchmarks/inmemory/verify.sh` (`pysrc/verify/`), its rule in `docs/verification.md`, its record in `artifacts/verification/ledger.psv` | `src/compareOutput.q` needs KDB-X (2 h for 9 solutions on `tiny` through the peachq shim), trusts one engine — DuckDB was wrong twice in one week — and its absolute 5e-5 float tolerance and order-sensitivity reported mostly noise. Nothing recorded that a published result was ever checked | Yes, in principle: it needs no KX product, and `compareOutput.q` stays |
| 26 | `polars.psv` / `polars_lazy.psv` idx 36–43 `std(ddof=0)` | q `dev` is the population deviation (qdocs `ref/dev.md:18`; `sdev` is the sample one, `:153`). Polars' `std()` is the sample one, so every `devSpread` was sqrt(n/(n-1)) high: idx 37 exchange Y, n = 22, 1.09908 for 1.07381 | Yes, standalone |
| 27 | `polars.psv` / `polars_lazy.psv` idx 39, 45–46 sum the sizes as `Int64` | `asize` and `bsize` are `Int32` and their sum wraps: ZSL's 3,014,324,600 summed to -1,280,642,696, so idx 46 answered -71.23 for 30.26. idx 39 has the same sum its twin idx 40 already widens; 45 the same as 46 | Yes, standalone |
| 28 | `polars.psv` / `polars_lazy.psv` idx 47–48 `rolling_mean(window_size=20, min_samples=1)` | q `mavg` averages the terms so far over the first items (qdocs `ref/avg.md:95`); Polars answered null for the first 19 rows. idx 49–50 already pass `min_samples=1` | Yes, standalone |
| 29 | `chdb.psv` idx 20–23, 49–50 divide with `divideOrNull` | 31 quotes of the infrequent instrument have `bsize + asize = 0`; ClickHouse's `0/0` is NaN and NaN poisons `avg`, where q's null is ignored (qdocs `ref/avg.md:24`). The same fix divergence 13 makes for DuckDB with a setting; chDB has no such setting | Yes, standalone |
| 30 | `duckdb.psv` idx 51–55 and `chdb.psv` idx 51–53 order their running windows `BY rowid`, not `BY time` | Rows tied on `time` came in an order the engine chose: DuckDB idx 54 was off on 4 rows tied on (sym, time) in every one of 3 runs, chDB idx 52 on row 11303 (21,283 trades, 19,118 distinct times). `rowid` is the table's stable time order, the order q's `sums` runs in (`docs/verification.md` section 3). idx 55 on chDB and 49–50 on both already used it | Yes, standalone |

### Verification rules

- **Consensus reference, one canonical form.** No engine is the reference: a query's golden is the answer at least
  three independent implementations share, and more share than disagree, else `unresolved`. Every output is reduced
  to the one canonical form of `docs/verification.md` before it is compared, and a translation that names its
  columns differently is fixed in the translation (divergence 24), not in the comparator.
- **Relative tolerance with a floor.** Floats agree within 1e-6 relative (floor 1e-9) plus the rounding their
  printing implies; a looser float32 allowance applies only where `artifacts/verification/float32.psv` lists a
  measurement for it.
- **Verification is separate and recorded.** It never runs inside a timed run, and every verified (solution, engine
  version, query file, parameters, date, size) is a row in `artifacts/verification/ledger.psv`; a published number
  without one is unverified.

### Development-machine results are not published

The one machine this fork can run on is a `12th Gen Intel(R) Core(TM) i7-12700H` laptop.
`convertToJSFormat.py` hard-errors on a CPU model missing from `results/mappings.yaml`, so
until it was added, **no dashboard data could be generated here at all** and every result
existed only as a PSV. The other two entries are server parts, and README promises publicly
that timings are "comparable: same hardware, or the numbers mean nothing".

Adding the laptop next to them silently would have broken that promise, so the entry comes
with both halves of the guard:

- **A name that states the class.** `DEV_INTEL_CORE_I7_12700H`, so the hardware page's machine
  selector reads as a dev box at a glance rather than as a third server.
- **An enforced rule.** `mappings.yaml` gained a `dev_machines:` list; `convertToJSFormat.py`
  drops those runs, names each directory it dropped, and **exits non-zero if that left nothing
  to write** rather than emitting an empty data file that looks like a successful publish.
  `--include-dev-machines` is the deliberate opt-in that makes the pipeline runnable here.

Rejected: a documented convention alone. Publishing already needs an explicit `git add -f`
(`results/` is gitignored), and a rule that only lives in prose fails exactly when someone is
in a hurry — which is when it matters. Also rejected: filtering by a `DEV_` name prefix, which
makes a publication decision turn on string matching; the list is data and says what it means.

`tools/publish.sh` passes `--include-dev-machines` deliberately: peachq.org/benchmark and its
drill-down name the laptop and say on the page that its numbers are not comparable with KX's
published server results (divergence 21).

The mechanism is fork-specific policy rather than a bug fix, so it is offerable upstream only
as a feature. Upstream has the same exposure the moment anyone benchmarks on a workstation.

### Where the splayed converter lives, and why

`generateDB.sh` is its home rather than a sibling script. It already dispatches on
`DATAFORMAT`, and its `rayforce` branch already resolves an engine binary and drives it — a
`splayed` branch that resolves `src/qengine/qbin.sh` is the same shape, one line of dispatch,
and it keeps "how do I build the data for engine X" a single question with a single answer. A
sibling script would have been a second place to look for the same thing.

The layout is `DST/sym`, `DST/exnames` and `DST/<date>/{master,trade,quote}/`, which is what
the kdb+ database looks like on disk, so `src/loadSplayedDataset.q` can follow
`loadKDBDBIntoMemory`'s shape. It is **not** a partitioned database: no `par.txt`, nothing is
loaded as a partitioned view, and the loader reads each splay by path. peachq does not do
partitioned databases and the in-memory suite does not need one — the date directory is there
so two dates cannot read each other's data, the same reason the `rayforce` branch has one.

Rejected: writing the tables at the database root with no date directory. It is marginally
simpler and makes the database silently wrong the first time anyone generates a second date
into it.

The converter has no `-batchsize`: it holds the day in memory, as parsing does anyway. That is
a real limit against `full`, and it is recorded here rather than discovered later.

### peachq gaps found building Stage B

All against the pinned v0.74.0. None blocked the work; each has a workaround in the tree.

| expression | peachq | kdb+ | worked around by |
|---|---|---|---|
| `string 0Nj` | `"0Nl"` | `""` | `nullStr` in `runQueries.lite.q` (divergence 10) |
| ``get `:db/2026.04.01/trade`` | `error: io` | the table | asking for `trade/`, with the trailing slash |
| ``` `time xasc get `:db/2026.04.01/trade/ ``` | `error: type` | the sorted table | `select ... where i>-1` first, which the shared runner does anyway |

The second and third only bite a table read straight off disk; the same expressions on an
in-memory table are fine. The third is why `src/loadSplayedDataset.q` materialises rather than
leaving the tables mapped — which is what the benchmark wants regardless, so the workaround
costs nothing and is not a divergence.

### Known verification reds on `tiny`

What `verify.sh` still reports on `tiny` (2026-07-01) after divergences 26–30, each with its measured cause. None
is a translation that asks a different question, so none is fixed here.

| Solution | idx | Verdict | Cause | Filed |
|---|---|---|---|---|
| peachq, peachq (via DuckDB) | 49–50 | value-diff | `xasc` broke time ties out of load order on tables past ~500k rows, so `5 mavg` ran over tied quotes in another order; root: under `\s 0` `iasc til 100000` was not `til 100000` | [timestored/openq#1041](https://github.com/timestored/openq/pull/1041), fixed there; green once the pin moves past it |
| Rayforce, Rayforce Parted | 61 | missing | `(prior == sy)` over a symbol vector is a `LIST`, not `B8`, so `where` rejects it (2.11.5; `rayforce.psv` was written for 2.5.11) | [RayforceDB/rayforce#966](https://github.com/RayforceDB/rayforce/issues/966) |
| Rayforce Parted | 53, 55 | value-diff | Not a Rayforce defect: the layout is sorted `sym,time`, and its running sum over every trade of one exchange is exactly the running sum in that order (all 142 / 63,939 rows). The question depends on physical order (`docs/verification.md` section 3); KDB-X (Parted) would answer the same | not filed |

On the fixture (2026-04-01) Pandas and chDB (Memory) also differ on idx 32–33 `avgSpread` by 1.5e-6 relative, as
they did before this change; it is not investigated here.

## Upstream ledger

Every fix offered to `KxSystems/NYSETAQBenchmarks`, and what happened.

| Offered | PR | What | Outcome |
|---|---|---|---|
| 2026-08-05 | [KxSystems#15](https://github.com/KxSystems/NYSETAQBenchmarks/pull/15) | Bump the `taq` submodule gitlink `ecf6daa` → `dcfc9c6` (divergence 1) | **merged** `ce8cc8e`, 2026-08-06 |
| 2026-08-05 | [KxSystems#16](https://github.com/KxSystems/NYSETAQBenchmarks/pull/16) | `duckdb.psv` idx 24–29: group on the aliased `minute` bucket, plus parameter inlining (divergence 2, 6) | **part-applied** as `9e40b75`; second commit declined |
| 2026-08-05 | [KxSystems#17](https://github.com/KxSystems/NYSETAQBenchmarks/pull/17) | Pin `duckdb` exactly in the PEP 723 block and `pyproject.toml` (divergence 3) | **declined**, with rationale |
| 2026-08-05 | [KxSystems#18](https://github.com/KxSystems/NYSETAQBenchmarks/pull/18) | README: `add_nickname` → `add_solution_name`, and the submodule note (divergence 4) | **merged** `345d42a`, 2026-08-06 |

### What the responses tell us

Three of four offers were taken in whole or in substance, within a day, from an outside
contributor. **Upstream accepts bug fixes readily**, and the fork's working assumption should
be that a defect found here is worth offering rather than hoarding. Whether upstream would
accept a *vendor engine* is a separate and still-untested question — PR #14, the Rayforce
adapter, has been open since 2026-08-02.

Two declines, both reasoned, both now recorded as deliberate divergences rather than
oversights:

- **#16, second commit** (parameter inlining for `pivot`-tagged queries): *"I consider the
  second commit to be a workaround to a DuckDB bug. DuckDB engineers are aware of this pivot,
  parsing issue."* Correct on the merits — it is a workaround. The fork keeps it because
  divergence 6 is what actually makes idx 24–29 return rows, and waiting on a DuckDB release
  means six queries stay dark. Upstream now has the `GROUP BY` fix without the inlining, so
  **upstream's idx 24–29 still error**; ours do not. Revisit when DuckDB fixes the underlying
  parser issue, and drop divergence 6 at that point.
- **#17** (pinning DuckDB): *"We intentionally don't pin versions in the inline script
  metadata… Results are published across a range of library versions, which users can look up
  in the `stats.yaml` files or via the hover tooltip at benchmark.kx.com."* A legitimate
  design choice for a suite publishing a moving picture of engine progress. This fork pins
  because **repeatable** is one of its three stated goals and an unpinned dependency makes a
  published number unreproducible. Divergence 3 is therefore permanent and deliberate, not a
  fix awaiting acceptance.

## Follow-ups recorded, not yet done

- **Delete `src/qengine/runQueries.lite.q`.** It exists only because `src/runQueries.q` cannot
  be *parsed* by a q implementation lacking three KDB-X syntactic features. Neither is
  reachable by a capability shim, and rewriting them in a shared file would be a fork of it
  rather than a divergence from it. Status against peachq:

  | feature | sites | 0.71 | 0.74 |
  |---|---|---|---|
  | progressive blocks in a conditional, `$[c;[a;b];…]` | 6 | parse error | **fixed** |
  | typed lambda params, `{[x:`C] …}` | 15 | parse error | parse error |
  | parameter destructuring, `{[(a;b)] …}` | 1 (`writeRes`, also typed) | parse error | parse error |

  Two of the three remain, so the lite runner stays for now. The `qlite` arm moves back onto
  `src/runQueries.q` as soon as an implementation parses all three; divergence 8 (the relaxed
  guard) is the prerequisite and is already in place. Until then the repo carries a third
  implementation of `docs/engine-contract.md` — exactly what the contract was written to stop —
  and the lite runner is documented as delete-only, not extend.
- ~~**`qlite` setup rows are not comparable with the kdb+ arms'.**~~ **Done**, by divergence
  12. The arm loads a splayed kdb database, so `idx 0` is a database load on both sides. The
  PSV path stays reachable with `-format psv` and keeps the caveat.
- **`qlite` reports `threadcount` 1 for every run.** peachq's `system "s"` is `0`, so the arm
  runs once for the first `--threads` value rather than once per value, which would emit
  duplicate `threadcount 1` rows and double the query list `convertToJSFormat.py` builds.

- **Rayforce onto the engine contract.** PR #14 was merged as-is at head
  `240964f4b8f66f06e74d7a2f2b493b8fa24eab93`; its `src/rayforce/runRayforce.sh` is a third
  parallel implementation of the runner contract. Phase 2 moves it onto
  `docs/engine-contract.md` as that contract's second consumer. Two specific deviations are
  already visible and must be settled by that move, not before it:
  - `src/rayforce/runQueries.rfl`'s `runq` executes each query **four** times: `run1`,
    `run2`, `run3`, then a fourth `measure` pass under `.mem.ts` that `run3memKB`,
    `ressizeKB` and the `queryoutput_<idx>.csv` are all taken from. Both existing runners
    execute three times and take memory, result size and output from the third. The three
    reported timings are still the first three runs, but `run3memKB` is not measured on run 3
    and the per-query workload is 4 executions rather than 3.
  - `src/compareOutput.q`, which PR #14 also rewrites, reads each CSV header with
    `first read0 (file; 0; 65536)`. That is the byte-range form of `read0`, which yields a
    character vector, so `first` selects a single character rather than the header line,
    where the code it replaces used `first system "head -n 1 …"`. Every other `read0` in this
    repo uses the line-oriented form. Flagged rather than fixed: confirming it, and any fix,
    requires executing KDB-X, which this fork's maintainer does not do (see `CONTRIBUTING.md`).
    It is also feedback to send to upstream PR #14 while it is open.
- **Rayforce arm verification.** Not executed; shape-checked only (`bash -n` over
  `src/rayforce/*.sh`, and `artifacts/queries/inmemory/rayforce.psv` confirmed 4-field and
  idx-aligned with `querymeta.psv`). Two independent blockers, both to be cleared in Phase 2:
  1. Its database generation path is not clean-room. `generateDB.sh`'s `rayforce` branch
     requires the sibling `kdb` database to exist and then runs
     `q ./src/rayforce/exportRayCSV.q` to bridge it to CSV, so producing a Rayforce DB needs
     a kdb+ binary.
  2. The pinned release artifact does not run on the development host. Release v2.5.11
     (`rayforce-2.5.11-linux-x86_64.tar.gz`, sha256 `8f63ca…8ccd`) was fetched and its
     checksum verified, but the binary requires `GLIBC_2.38` and the host provides 2.35.
     Phase 2's `scripts/fetch-engines.sh` therefore needs a glibc floor recorded per engine,
     or a container.
- **Vendor the taq submodule.** Phase 2. This will be the first divergence that is *not*
  offerable upstream, which is why it is deliberately not bundled with the bump in
  divergence 1.
- **`duckdb.psv` idx 24–29: resolved, with a disclosed mechanism difference.** Divergence 2
  fixed the unbindable `GROUP BY time`, which was masking a second, independent defect:
  DuckDB refuses a bound parameter in the source of a `PIVOT` whose pivot values are
  extracted from the data, on every version tested from 1.2.2 to 1.5.5. Isolated on 1.5.5:
  a bound parameter alone binds, a `PIVOT` with a literal binds, the combination does not.

  Divergence 6 resolves it by inlining the parameter as a SQL literal for queries tagged
  `pivot`, leaving the other 78 on bound parameters. **This is a real mechanism difference
  and is disclosed rather than hidden:** those six are executed as literal SQL while the rest
  are prepared. It is defensible because the q sibling has no bound parameters at all.
  `src/getQueryParameters.q` defines `freqInstr`, `fiftyInstrs` and friends as globals that
  `kdb.psv` references by name, so literal substitution is *closer* to what the q side does,
  not further from it. Enumerating the `ON` values was rejected as the alternative: for idx
  24–25 it would hard-code the exchange list the q sibling derives from the data, and for idx
  26–29 the pivot values *are* the parameter list.

  Result: all 84 queries return `status=success` for DuckDB for the first time. Output
  equivalence against the q sibling remains unestablished for these six and needs Phase 1's
  `qlite` seam.
- **`duckv2`.** A separate DuckDB query set, deliberately out of scope for Phases 0–2. The
  existing `duckdb.psv` queries are not to be improved or tuned in the meantime.
