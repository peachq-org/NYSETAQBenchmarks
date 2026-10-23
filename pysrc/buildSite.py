#!/usr/bin/env python3
"""Build the fork's hosted copy of the results dashboard.

    python pysrc/buildSite.py SIZE OUT_DIR [--title TITLE]

Copies index.html, its assets and the SIZE results into OUT_DIR, rewritten for
hosting outside kx.com: no KX analytics tag, consent button, logo or copyright,
repository links pointing at this fork, and credit to KX for the benchmark,
its queries and the dashboard. index.html itself stays as upstream ships it.
Run pysrc/convertToJSFormat.py on results/inmemory/SIZE first.
"""
import argparse
import re
import shutil
from pathlib import Path

FORK = "https://github.com/peachq-org/NYSETAQBenchmarks"
UPSTREAM = "https://github.com/KxSystems/NYSETAQBenchmarks"


def sub(text, old, new, count=1):
    if old not in text:
        raise SystemExit(f"buildSite: index.html no longer contains {old[:60]!r}; update the rewrite")
    return text.replace(old, new, count)


def rewrite(html, size, title):
    html = re.sub(r'\s*<script async src="https://www\.googletagmanager\.com/[^"]*"></script>\s*<script>.*?</script>',
                  "", html, count=1, flags=re.S)
    if "googletagmanager" in html:
        raise SystemExit("buildSite: the analytics tag is still in the page")
    html = sub(html, "<title>KX NYSE TAQ Benchmark — In-Memory Query Engines</title>", f"<title>{title}</title>")
    html = re.sub(r'<h1><a href="https://kx\.com".*?</svg></a> NYSE TAQ Benchmark — In-Memory Query Engines</h1>',
                  f"<h1>{title}</h1>", html, count=1, flags=re.S)
    html = sub(html, '<a href="https://kx.com/blog/the-kx-nyse-taq-benchmark/">Methodology and motivation</a>',
               '<a href="https://kx.com/blog/the-kx-nyse-taq-benchmark/">KX\'s methodology and motivation</a>')
    html = sub(html, f'<a href="{UPSTREAM}">Reproduce and validate results</a>',
               f'<a href="{FORK}">Reproduce and validate results</a>')
    html = sub(html, f'<a href="{UPSTREAM}#adding-a-new-python-based-in-memory-query-engine">Add a solution</a>',
               f'<a href="{FORK}#adding-a-new-python-based-in-memory-query-engine">Add a solution</a>')
    html = re.sub(r'\s*<a href="pages/(hardware|threadscaling)/index\.html">[^<]*</a>', "", html)
    html = re.sub(r'<div class="footer-copyright">.*?</div>',
                  '<div class="footer-copyright">The benchmark, its queries and this dashboard are '
                  f'<a href="{UPSTREAM}">KX\'s NYSE TAQ benchmark</a> (Apache-2.0). These runs come from '
                  f'<a href="{FORK}">the peachq-org fork</a> on a development laptop and are not comparable '
                  'with KX\'s published server results.</div>', html, count=1, flags=re.S)
    html = re.sub(r'\s*<nav id="footer-navigation".*?</nav>', "", html, count=1, flags=re.S)
    html = sub(html, "const available_sizes = ['full', 'xlarge', 'large'];", f"const available_sizes = ['{size}'];")
    html = sub(html, "const default_size = 'full';", f"const default_size = '{size}';")
    html = re.sub(r"const default_solutions = \[[^\]]*\];",
                  "const default_solutions = [... new Set(data.map(elem => elem.solution))];", html, count=1)
    html = sub(html, "const default_baseline = 'KDB-X';", "const default_baseline = 'DuckDB (Index)';")
    html = sub(html, f'link.href = "{UPSTREAM}";', f'link.href = "{FORK}";')
    for brand in ("googletagmanager", "©2026 KX", "kx-logo", "privacy-policy"):
        if brand in html:
            raise SystemExit(f"buildSite: {brand!r} is still in the page")
    return html


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("size")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--title", default="NYSE TAQ Benchmark — In-Memory Query Engines (peachq-org fork)")
    a = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    data = root / "results" / "inmemory" / a.size / "data.generated.js"
    if not data.is_file():
        raise SystemExit(f"buildSite: {data} is missing; run pysrc/convertToJSFormat.py first")
    out = a.out_dir
    if out.exists():
        shutil.rmtree(out)
    (out / "results" / "inmemory" / a.size).mkdir(parents=True)
    (out / "artifacts" / "queries" / "inmemory").mkdir(parents=True)
    shutil.copytree(root / "assets", out / "assets")
    shutil.copy2(data, out / "results" / "inmemory" / a.size / "data.generated.js")
    shutil.copy2(root / "artifacts/queries/inmemory/querymeta.generated.js", out / "artifacts/queries/inmemory/")
    for f in ("querymeta.psv", "tags.psv"):
        shutil.copy2(root / "artifacts/queries/inmemory" / f, out / "artifacts/queries/inmemory/")
    shutil.copy2(root / "LICENSE", out / "LICENSE")
    (out / "index.html").write_text(rewrite((root / "index.html").read_text(), a.size, a.title))
    # One thread is the count every solution ran at, the q implementations being single-threaded.
    js = out / "assets" / "js" / "benchmark.js"
    js.write_text(sub(js.read_text(), "const default_threads = '4';", "const default_threads = '1';"))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
