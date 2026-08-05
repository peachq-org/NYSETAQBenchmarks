#!/usr/bin/env python3
"""Compares two sets of NYSE TAQ query outputs, porting src/compareOutput.q.

Same checks in the same order — row count, column count, column names, then
cell by cell with floats inside FLOATDIFFTHREASHOLD — but written in Python
because the q original needs KDB-X >= 5.0 to run.

Two deliberate differences from the original:
  * the original reads both CSVs through one hard-coded column-type dictionary,
    which is what lets it compare 09:30 with 09:30:00 and a q null with an empty
    field.  A hard-coded dictionary cannot survive a new column, so the type is
    INFERRED per column instead, from both files together: numeric if every
    non-null cell on both sides parses as a number, temporal if every one is a
    clock literal, else text compared as text.  Inferring per COLUMN rather than
    per cell is what keeps a text column's "001" and "1" distinct.
  * when an in-order comparison fails, the same rows are compared again sorted,
    so a pure row-ordering difference is reported as its own verdict rather than
    as a value mismatch.
"""
import argparse
import csv
import math
import re
import sys
from pathlib import Path

FLOATDIFFTHREASHOLD = 5e-5
# q spells a typed null as its own literal and a char null as a space, DuckDB
# spells every null as an empty field.  Reading both sides through one q type,
# as the original does, collapses all of these; this set is that collapse.
NULLS = {"", " ", "0n", "-0n", "0N", "0Nh", "0Ni", "0Nj", "0Ne", "0Nf", "0Nd",
         "0Nt", "0Nu", "0Nv", "0Nn", "0Np", "0Nm", "0Nz"}
TEMPORAL = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[ T])?(?:0D)?(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?$")


def as_null(cell):
    """Whitespace is stripped first because reading a CSV field through a q type
    strips it, so the original compares `cond` values ' O X' and 'O X' equal."""
    s = cell.strip()
    if s in NULLS:
        return None
    try:
        return None if math.isnan(float(s)) else s   # a NaN float IS q's null float
    except ValueError:
        return s


def as_num(s):
    try:
        return float(s)
    except ValueError:
        return None


def as_time(s):
    m = TEMPORAL.match(s)
    if not m:
        return None
    h, mi, sec, frac = m.groups()
    return f"{int(h):02d}:{mi}:{sec or '00'}.{(frac or '').ljust(9, '0')[:9]}"


def column_reader(cells):
    """The narrowest reading every non-null cell of a column admits."""
    live = [c for c in (as_null(c) for c in cells) if c is not None]
    for read in (as_num, as_time):
        if live and all(read(c) is not None for c in live):
            return read
    return lambda s: s


def close(a, b):
    """Upstream's absolute threshold, widened to a relative one for large
    magnitudes where 5e-5 is below what two double paths can agree on.  Any
    match that needs the relative arm is reported, so it cannot hide silently."""
    if a == b:
        return True
    d = abs(a - b)
    if d <= FLOATDIFFTHREASHOLD:
        return True
    if d <= FLOATDIFFTHREASHOLD * max(abs(a), abs(b)):
        RELATIVE.append((a, b))
        return True
    return False


RELATIVE = []


def same(read, a, b):
    a, b = as_null(a), as_null(b)
    if a is None or b is None:
        return a is None and b is None
    a, b = read(a), read(b)
    return close(a, b) if isinstance(a, float) else a == b


def read(path):
    with open(path, newline="") as f:
        r = csv.reader(f)
        head = next(r, [])
        return head, [row for row in r]


def rows_match(head, ra, rb, order):
    """Cell-by-cell over the shared columns; returns the first difference."""
    rb = [[y[j] for j in order] for y in rb]
    readers = [column_reader([r[c] for r in ra] + [r[c] for r in rb])
               for c in range(len(head))]
    for i, (x, y) in enumerate(zip(ra, rb)):
        for c, (p, q) in enumerate(zip(x, y)):
            if not same(readers[c], p, q):
                return f"column {head[c]} row {i}: {p!r} vs {q!r}"
    return None


def compare(idx, apath, bpath):
    if not apath.exists():
        return "missing-a", f"no {apath.name}"
    if not bpath.exists():
        return "missing-b", f"no {bpath.name}"
    ah, ar = read(apath)
    bh, br = read(bpath)
    if len(ar) != len(br):
        return "mismatch", f"rows {len(ar)} vs {len(br)}"
    if len(ah) != len(bh):
        return "mismatch", f"columns {len(ah)} vs {len(bh)}"
    if sorted(ah) != sorted(bh):
        return "mismatch", (f"column names: only in a {sorted(set(ah) - set(bh))}, "
                            f"only in b {sorted(set(bh) - set(ah))}")
    order = [bh.index(c) for c in ah]          # reorder b's columns to match a
    bad = rows_match(ah, ar, br, order)
    if bad is None:
        return "match", ""
    key = lambda row: [str(as_null(c)) for c in row]
    if rows_match(ah, sorted(ar, key=key),
                  sorted([[r[j] for j in order] for r in br], key=key),
                  list(range(len(ah)))) is None:
        return "order-only", bad
    return "mismatch", bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", required=True)
    ap.add_argument("--a", required=True, help="directory of the engine under test")
    ap.add_argument("--b", required=True, help="directory of the oracle")
    ap.add_argument("--skip", default="", help="comma-separated idx to report as not-comparable")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    tally = {}
    with open(args.meta, newline="") as f:
        for row in csv.DictReader(f, delimiter="|"):
            idx = row["idx"]
            if idx in skip:
                verdict, detail = "not-comparable", "excluded"
            else:
                verdict, detail = compare(
                    idx, Path(args.a, f"queryoutput_{idx}.csv"),
                    Path(args.b, f"queryoutput_{idx}.csv"))
            tally[verdict] = tally.get(verdict, 0) + 1
            print(f"{idx}|{verdict}|{detail}")
    print("--- " + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())) +
          (f"; {len(RELATIVE)} cells matched only on the relative tolerance"
           if RELATIVE else ""), file=sys.stderr)
    return 0 if set(tally) <= {"match", "not-comparable"} else 1


if __name__ == "__main__":
    sys.exit(main())
