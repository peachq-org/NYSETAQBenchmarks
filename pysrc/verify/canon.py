"""Reads a queryoutput CSV into the canonical form of docs/verification.md."""
from dataclasses import dataclass
from pathlib import Path

import polars as pl

NULL_SPELLINGS = ["", "0n", "-0n", "nan", "-nan", "+nan", "null"]
NULL_PATTERN = r"^0N[a-z]?$"
INT_PATTERN = r"^[+-]?\d+$"
FLOAT_PATTERN = r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$"
INF_SPELLINGS = {"0w": float("inf"), "-0w": float("-inf"), "inf": float("inf"), "-inf": float("-inf"),
                 "+inf": float("inf"), "infinity": float("inf"), "-infinity": float("-inf")}
BOOL_SPELLINGS = {"true": 1, "false": 0, "1b": 1, "0b": 0}
TIME_PATTERN = r"^(?:(\d+)D)?(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?$"

INT, FLOAT, TEXT, NULL = "int", "float", "text", "null"
SLACK = "\0slack"


@dataclass
class Canon:
    """A canonical query output. `kinds` maps every column to INT, FLOAT, TEXT or NULL (all null); each FLOAT
    column `c` has a companion `c + SLACK` in `frame` holding each cell's printing slack."""
    frame: pl.DataFrame
    kinds: dict

    @property
    def columns(self):
        return [c for c in self.frame.columns if not c.endswith(SLACK)]

    @property
    def shape(self):
        return self.frame.height, tuple(sorted(self.columns))


def _null_mask(s: pl.Expr) -> pl.Expr:
    return s.is_null() | s.str.to_lowercase().is_in(NULL_SPELLINGS) | s.str.contains(NULL_PATTERN)


def _time_ns(s: pl.Expr) -> pl.Expr:
    g = s.str.extract_groups(TIME_PATTERN)
    part = lambda i: g.struct.field(str(i)).cast(pl.Int64).fill_null(0)
    frac = g.struct.field("5").fill_null("").str.pad_end(9, "0").cast(pl.Int64)
    ns = (((part(1) * 24 + part(2)) * 60 + part(3)) * 60 + part(4)) * 1_000_000_000 + frac
    return pl.when(s.is_null()).then(None).otherwise(ns)


def _float(s: pl.Expr) -> pl.Expr:
    low = s.str.to_lowercase()
    return pl.when(low.is_in(list(INF_SPELLINGS))).then(low.replace_strict(INF_SPELLINGS, default=None)) \
        .otherwise(s.cast(pl.Float64, strict=False))


def _slack(s: pl.Expr) -> pl.Expr:
    """Half a unit in the last place of a cell printed in fixed notation to six or more decimals, as the q
    runners' `.Q.f[6]` does; shorter or exponent forms are taken as exact (docs/verification.md)."""
    places = s.str.extract(r"^[+-]?\d+\.(\d{6,})$").str.len_chars().cast(pl.Float64)
    return (pl.lit(0.5) * pl.lit(10.0).pow(-places)).fill_null(0.0)


def _kind(cells: pl.Series) -> str:
    live = cells.drop_nulls()
    if live.is_empty():
        return NULL
    low = live.str.to_lowercase()
    if live.str.contains(INT_PATTERN).all():
        return INT
    if (live.str.contains(INT_PATTERN) | low.is_in(list(BOOL_SPELLINGS))).all():
        return "bool"
    if (live.str.contains(FLOAT_PATTERN) | low.is_in(list(INF_SPELLINGS))).all():
        return FLOAT
    if live.str.contains(TIME_PATTERN).all():
        return "time"
    return TEXT


def canonical(raw: pl.DataFrame) -> Canon:
    """`raw` is the file read with every column as text."""
    trimmed = raw.select(pl.col(c).str.strip_chars() for c in raw.columns)
    nulled = trimmed.select(pl.when(_null_mask(pl.col(c))).then(None).otherwise(pl.col(c)).alias(c)
                            for c in trimmed.columns)
    kinds, exprs = {}, []
    for c in nulled.columns:
        kind = _kind(nulled[c])
        col = pl.col(c)
        if kind == INT:
            exprs.append(col.cast(pl.Int64))
        elif kind == "bool":
            exprs.append(col.str.to_lowercase().replace_strict(BOOL_SPELLINGS, default=None, return_dtype=pl.Int64)
                         .fill_null(col.cast(pl.Int64, strict=False)).alias(c))
            kind = INT
        elif kind == "time":
            exprs.append(_time_ns(col).alias(c))
            kind = INT
        elif kind == FLOAT:
            exprs += [_float(col).alias(c), _slack(col).alias(c + SLACK)]
        else:
            exprs.append(col)
        kinds[c] = kind
    return Canon(nulled.select(exprs), kinds)


def read(path: Path) -> Canon:
    """A `.csv` or `.csv.zst`; polars decompresses zstd in memory, so nothing is written to disk."""
    if path.stat().st_size == 0:
        raise ValueError(f"{path.name} is empty")
    return canonical(pl.read_csv(path, infer_schema=False))
