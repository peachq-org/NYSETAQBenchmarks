#!/usr/bin/env python3
"""Runs the benchmark's DuckDB query corpus over the same sample data openq reads.

DuckDB is the oracle: upstream asserts the row-aligned duckdb.psv and kdb.psv
queries return identical output, so its answers stand in for kdb+ and no
proprietary binary is ever consulted.

Layout and conventions follow pysrc/queryrunner/executors/inmemory/duckdb_con.py:
timestamps are TIMESTAMP_NS built from the trade date, tables are ordered by
time, and CSV output renders timestamps as q timespan literals and booleans as
0/1 so both engines' files are directly comparable.

The schema and exchange names below are TRANSCRIBED from
external/kx/taq/taq/inputSchema.q (whose Python twin is pysrc/taqToParquet/
schemas.py), not read from either, because this runner builds the tables from
the raw PSVs rather than from the parquet database those files serve.  taq.q
states the same three tables in q; a schema change must be carried into both.
"""
import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DUCKDB = os.environ.get("DUCKDB_BIN") or shutil.which("duckdb") or str(
    Path.home() / ".local/bin/duckdb")

TRADE_COLS = [
    ("time", "N"), ("ex", "C"), ("sym", "S"), ("cond", "S"), ("size", "E"),
    ("price", "E"), ("stop", "S"), ("corr", "H"), ("seq", "I"), ("tradeId", "J"),
    ("source", "C"), ("tradeReportingFacility", "S"), ("participantTimestamp", "N"),
    ("tradeReportingFacilityTRFTimestamp", "N"), ("tradeThroughExemptIndicator", "B"),
]
QUOTE_COLS = [
    ("time", "N"), ("ex", "C"), ("sym", "S"), ("bid", "E"), ("bsize", "I"),
    ("ask", "E"), ("asize", "I"), ("cond", "C"), ("seq", "I"),
    ("nationalBBOIndicator", "C"), ("finraBBOIndicator", "C"),
    ("finraADFMpidIndicator", "C"), ("corr", "C"), ("source", "C"),
    ("retailInterestIndicator", "C"), ("shortSaleRestrictionIndicator", "C"),
    ("LULDBBOIndicator", "C"), ("SIPGeneratedMessageIdentifier", "C"),
    ("nationalBBOLULDIndicator", "C"), ("participantTimestamp", "N"),
    ("FINRAADFTimestamp", "N"), ("FINRAADFMarketParticipantQuoteIndicator", "C"),
    ("securityStatusIndicator", "C"),
]
# external/kx/taq/taq/inputSchema.q letter -> the DuckDB type it reads back as
SQL_TYPE = {"N": "VARCHAR", "C": "VARCHAR", "S": "VARCHAR", "E": "FLOAT",
            "I": "INTEGER", "H": "SMALLINT", "J": "BIGINT", "B": "BOOLEAN"}

EXNAMES = [
    ("A", "NYSE American"), ("B", "NASDAQ OMX BX"), ("C", "NYSE National"),
    ("D", "FINRA Alternative Display Facility"),
    ("I", "International Securities Exchange"), ("J", "Cboe EDGA Exchange"),
    ("K", "Cboe EDGX Exchange"), ("L", "Long-Term Stock Exchange"),
    ("M", "Chicago Stock Exchange"), ("N", "New York Stock Exchange"),
    ("P", "NYSE Arca"), ("S", "Consolidated Tape System"),
    ("T", "NASDAQ Stock Market"), ("Q", "NASDAQ Stock Exchange"),
    ("V", "The Investors' Exchange"), ("W", "Chicago Broad Options Exchange"),
    ("X", "NASDAQ OMX PSX"), ("Y", "Cboe BYX Exchange"), ("Z", "Cboe BZX Exchange"),
]

TAQ_FILES = {
    "trade": ["EQY_US_ALL_TRADE_20250701.psv"],
    "quote": ["SPLITS_US_ALL_BBO_Y_20250701.psv", "SPLITS_US_ALL_BBO_Z_20250701.psv"],
}


def sql_str(s):
    return "'" + s.replace("'", "''") + "'"


def duck(db, script):
    """Runs a SQL script in one CLI session, returning its stdout."""
    r = subprocess.run([DUCKDB, str(db)], input=script, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"duckdb failed: {r.stderr.strip()}\n--- script ---\n{script}")
    return r.stdout


def nanos_of_day(col):
    """TAQ clocks are HHMMSSnnnnnnnnn text; this is their nanosecond offset."""
    p = f"lpad({col}, 15, '0')"
    return (f"(substr({p}, 1, 2)::BIGINT * 3600 + substr({p}, 3, 2)::BIGINT * 60 + "
            f"substr({p}, 5, 2)::BIGINT) * 1000000000 + substr({p}, 7, 9)::BIGINT")


def read_source(path, cols, datadate):
    """A SELECT over one PSV landing the openq column names and types.

    The benchmark carries TAQ clocks as TIMESTAMP_NS on the trade date, the same
    make_timestamp_ns(epoch_ns(date) + time) the DuckDB executor builds.
    """
    names = ", ".join(sql_str(c) for c, _ in cols)
    proj = []
    for c, t in cols:
        if t == "N":
            proj.append(f"CASE WHEN nullif({c}, '') IS NULL THEN NULL ELSE make_timestamp_ns("
                        f"epoch_ns(DATE {sql_str(datadate)}) + {nanos_of_day(c)}) END AS {c}")
        elif t == "B":
            proj.append(f"({c} = '1') AS {c}")
        elif SQL_TYPE[t] == "VARCHAR":
            proj.append(c)
        else:
            proj.append(f"nullif({c}, '')::{SQL_TYPE[t]} AS {c}")
    return (f"SELECT {', '.join(proj)} FROM read_csv({sql_str(str(path))}, delim='|', "
            f"header=true, all_varchar=true, names=[{names}])")


def build(db, datadir, datadate, params):
    parts = ["SET preserve_insertion_order = true;"]
    for table, files in TAQ_FILES.items():
        cols = TRADE_COLS if table == "trade" else QUOTE_COLS
        union = " UNION ALL ".join(
            read_source(Path(datadir) / f, cols, datadate) for f in files)
        parts.append(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM ({union});")
        # the benchmark's canonical -sortcols time; rowid breaks ties as it does there
        parts.append(f"CREATE OR REPLACE TABLE {table} AS "
                     f"SELECT * FROM {table} ORDER BY time, rowid;")
    rows = ", ".join(f"({sql_str(e)}, {sql_str(n)})" for e, n in EXNAMES)
    parts.append(f"CREATE OR REPLACE TABLE exnames AS SELECT * FROM (VALUES {rows}) t(ex, name);")
    rows = ", ".join(f"({sql_str(b)}, {sql_str(t)})" for b, t in params["timeBuckets"])
    parts.append("CREATE OR REPLACE TABLE timeBuckets AS "
                 f"SELECT bucket, bound::TIME AS bound FROM (VALUES {rows}) t(bucket, bound);")
    duck(db, "\n".join(parts))


def load_params(pdir):
    p = Path(pdir)
    single = lambda f: p.joinpath(f).read_text().strip()
    listed = lambda f: [l.strip() for l in p.joinpath(f).read_text().splitlines() if l.strip()]
    buckets = []
    for line in p.joinpath("timeBuckets.txt").read_text().splitlines():
        if line.strip():
            name, bound = line.split("=", 1)
            buckets.append((name.strip(), bound.strip()[2:]))
    return {
        "freqInstr": single("freqInstr.txt"),
        "infreqInstr": single("infreqInstr.txt"),
        "fiftyInstrs": listed("fiftyInstrs.txt"),
        "thousandInfreqInstrs": listed("thousandInfreqInstrs.txt"),
        "datadate": single("datadate.txt"),
        "timeBuckets": buckets,
    }


def bind(query, parameter, params):
    """Substitutes $1..$n textually; the CLI has no parameter binding."""
    for i, name in enumerate((parameter or "").split(",")):
        name = name.strip()
        if not name:
            continue
        v = params[name]
        lit = (f"({', '.join(sql_str(s) for s in v)})" if isinstance(v, list)
               else f"DATE {sql_str(v)}" if name == "datadate" else sql_str(v))
        query = query.replace(f"${i + 1}", lit)
    return query


TIMER = re.compile(r"real ([0-9.]+)")


def run_query(db, idx, query, outdir):
    """Three runs (cold, warm, warm); the last result becomes the CSV."""
    script = ".timer on\n" + f"CREATE OR REPLACE TABLE res AS {query};\n" * 3
    times = TIMER.findall(duck(db, script))
    cols = duck(db, ".mode csv\n.headers off\nSELECT column_name, column_type FROM (DESCRIBE res);")
    repl = []
    for row in csv.reader(cols.splitlines()):
        if len(row) != 2:
            continue
        name, ctype = row
        if ctype.startswith("TIMESTAMP_NS"):
            repl.append(f"format('0D{{:02d}}:{{:02d}}:{{:02d}}.{{:09d}}', hour(\"{name}\"), "
                        f"minute(\"{name}\"), second(\"{name}\"), "
                        f"(epoch_ns(\"{name}\") % 1000000000)) AS \"{name}\"")
        elif ctype == "BOOLEAN":
            repl.append(f'"{name}"::INTEGER AS "{name}"')
    sel = f"SELECT * REPLACE ({', '.join(repl)}) FROM res" if repl else "SELECT * FROM res"
    out = Path(outdir) / f"queryoutput_{idx}.csv"
    duck(db, f"COPY ({sel}) TO {sql_str(str(out))} (FORMAT CSV, HEADER);")
    return [int(float(t) * 1e9) for t in times]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--params", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--data", help="TAQ PSV directory (default: the taq submodule's testdata)")
    args = ap.parse_args()

    params = load_params(args.params)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(args.db).unlink(missing_ok=True)
    datadir = Path(args.data) if args.data else Path(args.root) / "external/kx/taq/testdata"
    build(args.db, datadir, params["datadate"], params)

    qfile = Path(args.root) / "artifacts/queries/inmemory/duckdb.psv"
    timings = ["idx|status|run2timeNS|run3timeNS"]
    with open(qfile, newline="") as f:
        for row in csv.DictReader(f, delimiter="|"):
            idx, query = row["idx"], bind(row["query"].strip(), row["parameter"], params)
            try:
                t = run_query(args.db, idx, query, args.out)
                status, t2, t3 = "success", t[1] if len(t) > 1 else 0, t[2] if len(t) > 2 else 0
            except RuntimeError as e:
                status, t2, t3 = "error", 0, 0
                print(f"{idx}|error|{str(e).splitlines()[0]}", file=sys.stderr)
            else:
                print(f"{idx}|success|")
            timings.append(f"{idx}|{status}|{t2}|{t3}")
    Path(args.out, "timings.psv").write_text("\n".join(timings) + "\n")


if __name__ == "__main__":
    main()
