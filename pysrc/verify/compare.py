"""Compares canonical query outputs (docs/verification.md): alignment, tolerance, verdicts."""
import math
from dataclasses import dataclass

import polars as pl

from canon import FLOAT, INT, NULL, SLACK, TEXT, Canon

TIE = "\0tie"
MAX_TIES = 10_000
RTOL = 1e-6
ATOL = 1e-9

OK, ORDER_ONLY, VALUE_DIFF, SHAPE_DIFF = "ok", "order-only", "value-diff", "shape-diff"
MISSING, NOT_WRITTEN, UNRESOLVED = "missing", "not-written", "unresolved"


@dataclass
class Verdict:
    verdict: str
    evidence: str = ""


def unify(kinds: list) -> str:
    """The one kind every file's column can be read as, or None when one says text and another a number."""
    live = {k for k in kinds if k != NULL}
    if not live:
        return NULL
    if live <= {INT}:
        return INT
    if live <= {INT, FLOAT}:
        return FLOAT
    return TEXT if live == {TEXT} else None


def sort_keys(kinds: dict) -> list:
    """Every column, floats last: a float is only known within tolerance, so it decides the least."""
    return [n for n, k in kinds.items() if k != FLOAT] + [n for n, k in kinds.items() if k == FLOAT]


def align(canons: list, keep_order: bool) -> tuple:
    """Casts every frame's columns to their unified kind, puts the columns in name order and, unless the query's
    emitted order is part of its answer, sorts rows on every column, floats last. Columns whose kinds cannot be
    unified are returned separately rather than cast."""
    names = sorted(set().union(*(c.columns for c in canons)))
    kinds = {n: unify([c.kinds[n] for c in canons if n in c.kinds]) for n in names}
    clash = [n for n, k in kinds.items() if k is None]
    dtype = {INT: pl.Int64, FLOAT: pl.Float64, TEXT: pl.String, NULL: pl.String}
    frames = []
    for c in canons:
        present = [n for n in names if n in c.kinds]
        f = c.frame.select([pl.col(n).cast(dtype[kinds[n]]) if kinds[n] else pl.col(n) for n in present] +
                           [(pl.col(n + SLACK) if n + SLACK in c.frame.columns else pl.lit(0.0)).alias(n + SLACK)
                            for n in present if kinds[n] == FLOAT])
        if not keep_order and present:
            f = f.sort(sort_keys({n: kinds[n] for n in present}), nulls_last=True, maintain_order=True)
        frames.append(f)
    return frames, kinds, clash


def _close(kind: str, rtol: float) -> pl.Expr:
    """Cells x and y agree: equal, both null, or for floats within tolerance plus their printing slack sx, sy."""
    x, y = pl.col("x"), pl.col("y")
    same = (x == y).fill_null(False) | (x.is_null() & y.is_null())
    if kind != FLOAT:
        return same
    bound = pl.max_horizontal(pl.max_horizontal(x.abs(), y.abs()) * rtol, pl.lit(ATOL)) + pl.col("sx") + pl.col("sy")
    return same | (x.is_finite() & y.is_finite() & ((x - y).abs() <= bound)).fill_null(False)


def _agree(a: pl.DataFrame, b: pl.DataFrame, n: str, kind: str, rtol: dict) -> pl.Series:
    cells = {"x": a[n], "y": b[n]}
    if kind == FLOAT:
        cells.update(sx=a[n + SLACK], sy=b[n + SLACK])
    return pl.DataFrame(cells).select(_close(kind, rtol.get(n, RTOL))).to_series()


def _evidence(a: pl.DataFrame, b: pl.DataFrame, n: str, row: int) -> str:
    return f"{n} row {row}: {a[n][row]!r} vs {b[n][row]!r}"


def _close_cells(x, y, sx, sy, rtol: float) -> bool:
    """The scalar form of _close, for matching the few rows of a tie."""
    if x is None or y is None:
        return x is None and y is None
    return x == y or math.isfinite(x - y) and abs(x - y) <= max(max(abs(x), abs(y)) * rtol, ATOL) + sx + sy


def _matched(a: pl.DataFrame, b: pl.DataFrame, floats: list, rtol: dict) -> bool:
    """Pairs every row of `a` with a distinct row of `b` agreeing on every float column, greedily."""
    free = b.rows(named=True)
    for row in a.rows(named=True):
        hit = next((r for r in free if all(_close_cells(row[n], r[n], row[n + SLACK], r[n + SLACK], rtol.get(n, RTOL))
                                           for n in floats)), None)
        if hit is None:
            return False
        free.remove(hit)
    return True


def first_difference(a: pl.DataFrame, b: pl.DataFrame, kinds: dict, rtol: dict, sorted_rows=False) -> str:
    """Evidence for the first cell that differs, or "" when `a` and `b` agree; both are aligned the same way.

    For `sorted_rows`, rows that tie on every non-float column were put in order by their floats, and two
    engines' floats can order such a tie differently within tolerance; those ties are matched row by row."""
    columns = [c for c in a.columns if c in kinds]
    agree = {n: _agree(a, b, n, kinds[n], rtol) for n in columns}
    bad = ~pl.DataFrame(agree).select(pl.all_horizontal(pl.all())).to_series() if columns else pl.Series([], dtype=bool)
    if not bad.any():
        return ""
    first = next(n for n in columns if not agree[n].all())
    evidence = _evidence(a, b, first, agree[first].arg_min())
    floats = [n for n in columns if kinds[n] == FLOAT]
    exact = [n for n in columns if kinds[n] != FLOAT]
    if not sorted_rows or not floats or not exact:
        return evidence
    tied = pl.concat([a.filter(bad).select(exact), b.filter(bad).select(exact)]).unique()
    if tied.height > MAX_TIES:
        return evidence
    groups = {k: g for k, g in b.join(tied, on=exact, nulls_equal=True).partition_by(exact, as_dict=True).items()}
    for key, group in a.join(tied, on=exact, nulls_equal=True).partition_by(exact, as_dict=True).items():
        other = groups.get(key)
        if other is None or other.height != group.height or not _matched(group, other, floats, rtol):
            return evidence
    return ""


def ties(golden: pl.DataFrame, keys: list, kinds: dict, rtol: dict) -> pl.Series:
    """Numbers the runs of the golden's rows that tie on the sort keys. Keys after the first float key are not
    used: a float key is only known to within tolerance, so the order a later key gives inside it is not either."""
    used = []
    for k in (k for k in keys if k in kinds):
        used.append(k)
        if kinds[k] == FLOAT:
            break
    breaks = pl.Series([False] * golden.height)
    for k in used:
        breaks = breaks | ~_agree(golden, golden.select(pl.all().shift(1)), k, kinds[k], rtol)
    return breaks.cum_sum()


def compare(golden: Canon, candidate: Canon, order, rtol: dict) -> Verdict:
    """`order` is None when row order is not part of the answer, else the query's sort keys; `rtol` maps a column
    to the relative tolerance it is compared at, RTOL when absent."""
    g_rows, g_names = golden.shape
    c_rows, c_names = candidate.shape
    if g_names != c_names:
        extra, lacking = sorted(set(c_names) - set(g_names)), sorted(set(g_names) - set(c_names))
        return Verdict(SHAPE_DIFF, f"columns: extra {extra[:5]} missing {lacking[:5]}")
    if g_rows != c_rows:
        return Verdict(SHAPE_DIFF, f"rows: {c_rows} vs {g_rows}")
    (g, c), kinds, clash = align([golden, candidate], keep_order=order is not None)
    if clash:
        return Verdict(VALUE_DIFF, f"{clash[0]}: text vs number")
    diff = first_difference(c, g, kinds, rtol, sorted_rows=order is None)
    if not diff:
        return Verdict(OK)
    if order is None:
        return Verdict(VALUE_DIFF, diff)
    tie = ties(g, order, kinds, rtol).alias(TIE)
    within = [f.with_columns(tie).sort([TIE] + sort_keys(kinds), nulls_last=True, maintain_order=True) for f in (g, c)]
    if not first_difference(within[1], within[0], {**kinds, TIE: INT}, rtol, sorted_rows=True):
        return Verdict(OK)
    (gs, cs), _, _ = align([golden, candidate], keep_order=False)
    return Verdict(ORDER_ONLY if not first_difference(cs, gs, kinds, rtol, sorted_rows=True) else VALUE_DIFF, diff)
