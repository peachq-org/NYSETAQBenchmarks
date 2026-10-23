"""Which implementation each benchmark solution is, and the query file it runs (as in queryEngines.sh and
kdbAttributes.sh)."""
import re

QUERIES = "artifacts/queries/inmemory/"

# solution -> (implementation, query file). Solutions of one implementation are one vote in the consensus:
# they share an engine and differ only in layout, index or API.
SOLUTIONS = {
    "KDB-X": ("kdb", "kdb.psv"),
    "KDB-X (Parted)": ("kdb", "kdb.psv"),
    "KDB-X (Manual Opt)": ("kdb", "kdb_manualopt.psv"),
    "KDB-X (NoAttr)": ("kdb", "kdb_noattr.psv"),
    "KDB-X (Time Sorted)": ("kdb", "kdb_noattr.psv"),
    "KDB-X (Table Dict)": ("kdb", "kdb_tabledict.psv"),
    "KDB-X (Table Dict Peach)": ("kdb", "kdb_tabledict.psv"),
    "KDB-X SQL": ("kdb", "sql.psv"),
    "pykx": ("kdb", "pykx.psv"),
    "DuckDB (No index)": ("duckdb", "duckdb.psv"),
    "DuckDB (Sym, Time Sort)": ("duckdb", "duckdb.psv"),
    "DuckDB (Index)": ("duckdb", "duckdb.psv"),
    "chDB (Memory)": ("chdb", "chdb.psv"),
    "chDB (Memory, Compressed)": ("chdb", "chdb.psv"),
    "chDB (PyArrow)": ("chdb", "chdb.psv"),
    "Polars (Eager)": ("polars", "polars.psv"),
    "Polars (Lazy)": ("polars", "polars_lazy.psv"),
    "Pandas": ("pandas", "pandas.psv"),
    "peachq": ("peachq", "kdb.psv"),
    "peachq (via DuckDB)": ("peachq", "kdb.psv"),
    "l": ("l", "kdb.psv"),
    "Rayforce": ("rayforce", "rayforce.psv"),
    "Rayforce Parted": ("rayforce", "rayforce.psv"),
}


def safe(solution: str) -> str:
    """The per-solution directory name run_solution in common.sh gives a solution."""
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", solution)


BY_DIR = {safe(s): s for s in SOLUTIONS}


def implementation(solution: str) -> str:
    return SOLUTIONS.get(solution, (solution, None))[0]


def query_file(solution: str):
    entry = SOLUTIONS.get(solution)
    return QUERIES + entry[1] if entry else None
