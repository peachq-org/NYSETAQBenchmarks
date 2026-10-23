# Common workloads (idx 101+)

KX's 84 queries are KX's benchmark: this fork fixes translations of them (`FORK.md`) but adds no query to them.
It adds a second, separate set of nine queries, idx 101 to 109, for TAQ work the 84 do not cover. They live in
their own files, run as their own invocation, are verified by the same rule, and are scored and published on their
own. They are never mixed into the 84, their times, or their MPH.

## Why a second set

Of KX's 84, 62 filter to one symbol or a symbol list first, where a `g#`/`p#` sym attribute answers by index; most of
the other 22 cut by a time window first, a binary search on a time-sorted table. All six as-of joins are restricted
(size > 500,000, a ten-minute window, or a symbol set), the `master` reference table is never queried, and there are
no window joins, equi-joins to reference data, returns or full-day bars for every symbol. Those are everyday TAQ
workloads. The set below runs them over the whole day.

## Where it lives

| What | Where |
|---|---|
| Queries, one file per engine | `artifacts/queries/inmemory/extra/{kdb,duckdb,chdb,polars,polars_lazy,pandas}.psv` |
| Metadata, with each definition in `comment` | `artifacts/queries/inmemory/extra/querymeta.psv` |
| Tags the set adds | `artifacts/queries/inmemory/extra/tags.psv` |
| Run | `queryEngines.sh --queryset extra ...` |
| Verify | `verify.sh --queryset extra ...` (golden under `DATA/verification/<size>_<date>_<params>_extra/`) |
| Publish | `tools/publish.sh ... --extra-results DIR --extra-verdicts FILE` |

A solution whose file is absent from `extra/` (today Rayforce, which has no Rayfall translation) is skipped by the
driver and shown as "not written". `kdb.psv` runs on peachq, peachq (via DuckDB) and l, through the lite runner.

## Definitions

These are the contract every translation answers; `querymeta.psv` carries the same text. Throughout:

- **Table order** is `time`, ties kept in load order: what `xasc` gives in q and `rowid` in DuckDB and chDB.
- **Arithmetic is float64.** `price`, `size`, `bid` and `ask` are float32 in the data and are widened before any
  sum, product or difference. A float32 `bid + ask` alone is off by ~2e-6 absolute on a $30 stock, against a spread
  near 0.01.
- **Volume is a float64 sum of `size`.** TAQ sizes can be fractional (12,075 trades on `tiny` are) and can be 0, so a
  sum of integers would be a different answer.
- **A minute bucket** is `time` floored to the minute, labelled by its start; only buckets with a trade exist.
- **Nothing is filtered** unless the definition says so: every trade, every quote, pre- and post-market included.

| idx | Query | Definition |
|---|---|---|
| 101 | One-minute OHLCV bars, every symbol | By sym and minute: open and close are the price of the bucket's first and last trade in table order; high and low the max and min price; volume the sum of size. |
| 102 | Daily summary per symbol | By sym: vwap = sum(price * size) / sum(size); volume = sum(size); trades = count; high and low = max and min price. |
| 103 | Every trade with its prevailing quote | The prevailing quote is the last quote of the same sym with quote time <= trade time; quotes tied on (sym, time) resolve to the last in table order (as idx 79-84). effSpread = 2 * abs(price - (bid + ask) / 2). No prevailing quote: bid, ask and effSpread null. Quotes are taken as they are, one-sided ones (bid or ask 0) included. |
| 104 | Window join | maxBid and minAsk are the max bid and min ask of the quotes of the same sym with trade time - 1s <= quote time <= trade time + 1s. Only quotes inside the window count: q `wj1`, not `wj`, which also counts the quote prevailing at the window's start. No quote in the window: null. |
| 105 | Volume by security type | Trades left-joined to `master` on sym, grouped by `securityType`: volume = sum(size), trades = count. Trades whose sym has no master row (`ZTST` on `tiny`) form the null group. |
| 106 | Odd lots by exchange | Trades with size < 100 and 10 <= price <= 100, counted by ex. An exchange with none does not appear. |
| 107 | Ten largest trades per symbol | Within each sym, trades ranked by size descending, ties by time ascending then table order; `sizeRank` counts from 1; rows with sizeRank <= 10 are kept. |
| 108 | Distinct symbols per exchange | Over the quote table: symCount = number of distinct syms per ex. |
| 109 | One-minute log returns and realised volatility | Per sym, close = last price in table order of each non-empty minute; ret = ln(close / previous non-empty minute's close); empty minutes are not filled and the first has no return. Per sym with a return: nret = number of returns, rvol = 10000 * population standard deviation (divisor n, q `dev`), basis points per bar. |

Two scale choices are verification choices, not finance ones. `rvol` is in basis points because the q runners print
floats to six decimals (`docs/verification.md` section 2): a deviation of 0.000371 printed that way keeps three
digits, and 3.705121 keeps seven. `effSpread` stays in price units, since a spread relative to the mid divides by
zero on a quote whose bid and ask are both 0; its q print is checked at the looser six-decimal slack.

## Translation notes

- **104 in DuckDB** is a range join on one composite key, `enum_code(sym::sym_enum) * 1e14` plus nanoseconds since
  midnight, so DuckDB plans an inequality join (IEJoin): 4.3 s at 4 threads on `tiny`. Written as `q.sym = t.sym AND
  q.time BETWEEN ...` it plans a hash join on sym with the range as a filter, 2 min 22 s on all cores; as a `RANGE`
  window over trades and quotes unioned, 45 s. The cast to `sym_enum` makes the shared enum (the executor's default,
  `SYMENUMBYTABLE` unset) a requirement that fails loudly rather than a coincidence that could fail silently.
- **104 in chDB, Polars and pandas** unions trades (with null bid/ask) and quotes, takes a centred one-second `RANGE`
  window per sym (`max(bid) OVER (... RANGE BETWEEN 1e9 PRECEDING AND 1e9 FOLLOWING)`, `Expr.rolling(...).over("sym")`,
  `groupby("sym").rolling("2s", center=True, closed="both")`), and keeps the trade rows.
- **103 in DuckDB and chDB** keeps the last quote of each (sym, time) with `QUALIFY row_number() ... = 1` before the
  `ASOF` join, as KX's idx 79 does; chDB also sets `join_use_nulls = 1`, or a trade without a quote reads 0, not null.
- **107** ranks by `size DESC, rowid` in SQL, by an ordinal rank over table order in Polars and pandas, and by
  `iasc idesc size` in q; the column is `sizeRank` because `rank` is a q keyword.

## Status on `tiny` (2026-07-01) and the fixture (2026-04-01)

Every query has a consensus of at least five implementations (DuckDB, chDB, Polars, Pandas, peachq; l on all but
104). Not `ok`, each a `missing` with the engine's error, not a different answer:

| Solution | idx | Error | Cause |
|---|---|---|---|
| l | 104 | `wj1` | l has no `wj1` |
| peachq (via DuckDB) | 104, 105 | `type` | peachq 0.89.0 cannot `wj1` or `lj` against a table linked from DuckDB |

NBBO construction (the national best bid and offer across exchanges) is deliberately not in this set: building it
correctly needs the quote-condition and exchange-eligibility rules, which would make the definition, not the engines,
the thing under test.
