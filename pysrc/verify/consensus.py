"""The consensus golden of one query, and every solution's verdict against it (docs/verification.md)."""
from dataclasses import dataclass, field

import polars as pl

from canon import FLOAT, INT, NULL, SLACK, TEXT, Canon
from compare import OK, UNRESOLVED, Verdict, align, compare, first_difference

MIN_AGREEING = 3


@dataclass
class Outcome:
    golden: Canon = None
    agreeing: list = field(default_factory=list)
    evidence: str = ""


def _same(a: Canon, b: Canon, order, rtol: dict) -> bool:
    return compare(a, b, order, rtol).verdict == OK


def classes(answers: dict, order, rtol: dict) -> list:
    """Partitions solutions into classes of equal answers, each a list whose first member is its representative.
    Solutions of one shape are aligned together once, so a query's large outputs are sorted once each; where
    order is part of the answer, or a column's kinds clash, each pair is compared on its own."""
    by_shape = {}
    for name in sorted(answers):
        by_shape.setdefault(answers[name].shape, []).append(name)
    found = []
    for names in by_shape.values():
        frames, kinds, clash = align([answers[n] for n in names], keep_order=order is not None)
        aligned = dict(zip(names, frames))
        mine = []
        for n in names:
            same = (lambda r: _same(answers[r], answers[n], order, rtol)) if clash or order is not None else \
                (lambda r: not first_difference(aligned[r], aligned[n], kinds, rtol, sorted_rows=True))
            home = next((c for c in mine if same(c[0])), None)
            home.append(n) if home else mine.append([n])
        found += mine
    return found


def precision(c: Canon) -> float:
    """Total printing slack: the representative of a golden class is its most precisely printed member."""
    slack = [s for s in c.frame.columns if s.endswith(SLACK)]
    return c.frame.select(pl.sum_horizontal(pl.col(slack).sum())).item() if slack else 0.0


def decide(answers: dict, implementation, order, rtol: dict) -> Outcome:
    """`answers` maps solution -> Canon. The golden is the answer of a class backed by at least MIN_AGREEING
    implementations, and by more implementations than answered anything else."""
    found = classes(answers, order, rtol)
    answering = {implementation(n) for n in answers}
    backing = [{implementation(n) for n in c} for c in found]
    ranked = sorted(range(len(found)), key=lambda i: -len(backing[i]))
    summary = "; ".join(f"{sorted(backing[i])} {len(found[i])} solution(s)" for i in ranked)
    best = [i for i in ranked if len(backing[i]) == len(backing[ranked[0]])] if ranked else []
    if len(best) != 1 or len(backing[best[0]]) < MIN_AGREEING or \
            len(backing[best[0]]) <= len(answering - backing[best[0]]):
        return Outcome(evidence=f"no majority: {summary}" if found else "no answers")
    winners = found[best[0]]
    rep = min(winners, key=lambda n: precision(answers[n]))
    return Outcome(answers[rep], winners, summary)


def judge(golden: Canon, answers: dict, agreeing: list, order, rtol: dict) -> dict:
    return {n: Verdict(OK) if n in agreeing else compare(golden, c, order, rtol) for n, c in answers.items()}


def unresolved(answers: dict, evidence: str) -> dict:
    return {n: Verdict(UNRESOLVED, evidence) for n in answers}


def from_frame(frame: pl.DataFrame) -> Canon:
    """A stored golden back into a Canon: its kinds are its dtypes."""
    def kind(c):
        s = frame[c]
        if s.dtype == pl.Int64:
            return INT
        if s.dtype == pl.Float64:
            return FLOAT
        return NULL if s.null_count() == s.len() else TEXT
    return Canon(frame, {c: kind(c) for c in frame.columns if not c.endswith(SLACK)})
