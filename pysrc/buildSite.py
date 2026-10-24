#!/usr/bin/env python3
"""Build the fork's hosted copy of the results dashboard.

    python pysrc/buildSite.py SIZE OUT_DIR [--title TITLE] [--data FILE] [--note TEXT]

Copies index.html, its assets and the SIZE results into OUT_DIR, rewritten for
hosting outside kx.com: no KX analytics tag, consent button, logo, copyright,
palette or kx.com link, repository links pointing at this fork, credit to KX
for the benchmark, its queries and the dashboard, and the peachq.org theme
(its colour tokens, light and dark, and font stacks). index.html itself stays
as upstream ships it. Run pysrc/convertToJSFormat.py on results/inmemory/SIZE
first, or pass the data.generated.js to copy with --data. --note adds a sentence
to the footer, saying how the data differs from KX's.
"""
import html as markup
import argparse
import re
import shutil
from pathlib import Path

FORK = "https://github.com/peachq-org/NYSETAQBenchmarks"
UPSTREAM = "https://github.com/KxSystems/NYSETAQBenchmarks"
KX_PALETTE = ("#FFCB22", "#D5A600", "#2159B2", "#3272D9", "#A8C5F0", "#112E5D", "#DAE6F9", "#F1F6FD",
              "#B3CBF1", "#FFE799", "#584300", "#7A6420")
KX_MARKS = ("googletagmanager", "GTM-", "©", "KX®", "kx-logo", "kx.com", "privacy-policy", "OneTrust",
            "cookie-settings")

# The peachq.org tokens (static/css/styles.css of the website) mapped onto the dashboard's.
PEACHQ_LIGHT = """:root {
  --color: #101217;
  --title-color: #101217;
  --background-color: #fbfbf8;
  --link-color: #b5531f;
  --link-hover-color: #f28b57;
  --hashed-link-lightness: 0.5;
  --selector-text-color: #3a3f47;
  --selector-active-text-color: #101217;
  --selector-background-color: #efeee9;
  --selector-active-background-color: #ffb38a;
  --selector-passive-text-color: #9a4a20;
  --selector-passive-background-color: #fff1e8;
  --selector-hover-text-color: #101217;
  --selector-hover-background-color: #ffd5bd;
  --summary-every-other-row-color: #f4f3ee;
  --highlight-color: #efeee9;
  --chart-scale-1: #f28b57;
  --chart-scale-2: #ffd2b8;
  --failed-bar: #d4d6da;
  --failed-color: #636973;
  --tooltip-text-color: #f4f5f7;
  --tooltip-background-color: #101217;
  --tooltip-border-color: #636973;
  --nothing-selected-color: #d4d6da;
  --shadow-color: #a5a9b0;
  --series-1: #f28b57;
  --series-2: #4d73ff;
  --series-3: #6b4fb3;
  --series-4: #2c8b57;
  --series-5: #9b5b00;
  --series-6: #a63772;
  --series-7: #3d6f91;
  --series-8: #63722b;
}"""
PEACHQ_DARK = """[data-theme=dark] {
  --color: #f4f5f7;
  --title-color: #ffffff;
  --background-color: #0d1014;
  --link-color: #ffb38a;
  --link-hover-color: #ffffff;
  --hashed-link-lightness: 0.82;
  --selector-text-color: #f4f5f7;
  --selector-active-text-color: #101217;
  --selector-background-color: #1d2229;
  --selector-active-background-color: #ffb38a;
  --selector-passive-text-color: #ffd2b8;
  --selector-passive-background-color: #3a2619;
  --selector-hover-text-color: #101217;
  --selector-hover-background-color: #ffd2b8;
  --summary-every-other-row-color: #12161b;
  --highlight-color: #1d2229;
  --chart-scale-1: #ffb38a;
  --chart-scale-2: #8a5638;
  --failed-bar: #3a4049;
  --failed-color: #9da4ae;
  --tooltip-text-color: #101217;
  --tooltip-background-color: #f4f5f7;
  --tooltip-border-color: #9da4ae;
  --nothing-selected-color: #3a4049;
  --shadow-color: black;
  --series-1: #ffb38a;
  --series-2: #86a1ff;
  --series-3: #dc9cff;
  --series-4: #52c07a;
  --series-5: #ffd27a;
  --series-6: #ff94c9;
  --series-7: #9ebcff;
  --series-8: #c4dc77;
}"""
SANS = 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
MONO = "ui-monospace, SFMono-Regular, Consolas, monospace"


def sub(text, old, new, count=1):
    if old not in text:
        raise SystemExit(f"buildSite: the upstream copy no longer contains {old[:60]!r}; update the rewrite")
    return text.replace(old, new, count)


def theme(css):
    css = sub_re(css, r"^:root \{.*?^\}", PEACHQ_LIGHT)
    css = sub_re(css, r"^\[data-theme=dark\] \{.*?^\}", PEACHQ_DARK)
    css = re.sub(r"/\*[^*]*(?:\*(?!/)[^*]*)*(KX|kx\.com|Euclid)[^*]*(?:\*(?!/)[^*]*)*\*/", "", css)
    css = re.sub(r"\n[^{}\n]*(kx-logo|footer-cookie-settings)[^{}]*\{[^}]*\}", "", css)
    css = sub(css, 'font-family: "Inter", Arial, sans-serif;', f"font-family: {SANS};")
    css = sub(css, 'Consolas, Monaco, "Andale Mono", "Ubuntu Mono", monospace', MONO, count=-1)
    return css.replace("#112E5D", "#b5531f").replace("#FFCB22", "#ffb38a")


def sub_re(text, pattern, new):
    out, n = re.subn(pattern, lambda _: new, text, count=1, flags=re.S | re.M)
    if n != 1:
        raise SystemExit(f"buildSite: the upstream copy no longer matches {pattern!r}; update the rewrite")
    return out


def rewrite(html, size, title, note=""):
    html = re.sub(r'\s*<script async src="https://www\.googletagmanager\.com/[^"]*"></script>\s*<script>.*?</script>',
                  "", html, count=1, flags=re.S)
    if "googletagmanager" in html:
        raise SystemExit("buildSite: the analytics tag is still in the page")
    html = re.sub(r'\s*<link [^>]*fonts\.(googleapis|gstatic)\.com[^>]*>', "", html)
    html = sub(html, "<title>KX NYSE TAQ Benchmark — In-Memory Query Engines</title>", f"<title>{title}</title>")
    html = re.sub(r'<h1><a href="https://kx\.com".*?</svg></a> NYSE TAQ Benchmark — In-Memory Query Engines</h1>',
                  f"<h1>{title}</h1>", html, count=1, flags=re.S)
    html = re.sub(r'\s*<a href="https://kx\.com/blog/[^"]*">Methodology and motivation</a>', "", html, count=1)
    html = sub(html, f'<a href="{UPSTREAM}">Reproduce and validate results</a>',
               f'<a href="{FORK}">Reproduce and validate results</a>')
    html = sub(html, f'<a href="{UPSTREAM}#adding-a-new-python-based-in-memory-query-engine">Add a solution</a>',
               f'<a href="{FORK}#adding-a-new-python-based-in-memory-query-engine">Add a solution</a>')
    html = re.sub(r'\s*<a href="pages/(hardware|threadscaling)/index\.html">[^<]*</a>', "", html)
    html = re.sub(r'<div class="footer-copyright">.*?</div>',
                  '<div class="footer-copyright">The benchmark, its queries and this dashboard are '
                  f'<a href="{UPSTREAM}">KX\'s NYSE TAQ benchmark</a> (Apache-2.0). These runs come from '
                  f'<a href="{FORK}">the peachq-org fork</a> on a development laptop and are not comparable '
                  'with KX\'s published server results.'
                  + (f" {markup.escape(note[0].upper() + note[1:])}." if note else "") + '</div>',
                  html, count=1, flags=re.S)
    html = re.sub(r'\s*<nav id="footer-navigation".*?</nav>', "", html, count=1, flags=re.S)
    html = sub(html, "const available_sizes = ['full', 'xlarge', 'large'];", f"const available_sizes = ['{size}'];")
    html = sub(html, "const default_size = 'full';", f"const default_size = '{size}';")
    html = re.sub(r"const default_solutions = \[[^\]]*\];",
                  "const default_solutions = [... new Set(data.map(elem => elem.solution))];", html, count=1)
    html = sub(html, "const default_baseline = 'KDB-X';", "const default_baseline = 'DuckDB (Index)';")
    html = sub(html, f'link.href = "{UPSTREAM}";', f'link.href = "{FORK}";')
    return html


def assert_unbranded(out):
    for path in sorted(p for p in out.rglob("*") if p.suffix in (".html", ".css", ".js")):
        text = path.read_text()
        for mark in KX_MARKS + KX_PALETTE:
            if mark.lower() in text.lower():
                raise SystemExit(f"buildSite: {mark!r} is still in {path.relative_to(out)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("size")
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--title", default="NYSE TAQ Benchmark — In-Memory Query Engines (peachq-org fork)")
    ap.add_argument("--data", type=Path, help="data.generated.js to copy (default: results/inmemory/SIZE/)")
    ap.add_argument("--note", default="", help="a sentence for the footer on how this data differs from KX's")
    a = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    data = a.data or root / "results" / "inmemory" / a.size / "data.generated.js"
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
    (out / "index.html").write_text(rewrite((root / "index.html").read_text(), a.size, a.title, a.note))
    # One thread is the count every solution ran at, the q implementations being single-threaded.
    js = out / "assets" / "js" / "benchmark.js"
    js_text = sub(js.read_text(), "const default_threads = '4';", "const default_threads = '1';")
    js.write_text(sub_re(js_text, r"^    const cookieSettingsButton = .*?^    \}\);\n\n", ""))
    css = out / "assets" / "css" / "benchmark.css"
    css.write_text(theme(css.read_text()))
    assert_unbranded(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
