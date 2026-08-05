/ Runs the benchmark's q query corpus under openq: three runs per query
/ (cold, warm, warm), the last result written as queryoutput_<idx>.csv.

system "l ", getenv[`OPENQ_DIR], "/taq.q"
paramDir: taqEnv[`TAQ_PARAMS; taqRoot, "/openq/params"]
outDir: taqEnv[`TAQ_OUT; taqRoot, "/openq/out-q"]
queryFile: taqEnv[`TAQ_QUERIES; taqRoot, "/artifacts/queries/inmemory/kdb.psv"]

rd: {[f] read0 hsym `$paramDir, "/", f}
freqInstr: first `$rd "freqInstr.txt"
infreqInstr: first `$rd "infreqInstr.txt"
fiftyInstrs: `$rd "fiftyInstrs.txt"
thousandInfreqInstrs: `$rd "thousandInfreqInstrs.txt"
timeBuckets: asc (!/) (`$; "N"$) @' flip "=" vs/: rd "timeBuckets.txt"
/ `s# on a dictionary is the step-function idiom (kb/temporal-data.md); where the
/ engine cannot set it the lookup degrades to exact match and query 63 diverges.
timeBucketsStep: @[{`s# x}; value[timeBuckets]!key timeBuckets;
  {[d; e] -1 "WARN: `s# on a dictionary failed (", e, ") - step lookup degraded"; d}
    [value[timeBuckets]!key timeBuckets]]

/ float and real columns are written at the 6dp the benchmark's comparator assumes;
/ a nested column is rendered verbatim, so a divergent item shows up as a diff
txt: {$[10h = type x; x; -10h = type x; enlist x; -3! x]}
cell: {$[0h = type x; `$ txt each x;
         abs[type x] in 8 9h; .Q.f[6] each x * 1.0; x]}
persist: {[res; idx]
  (hsym `$outDir, "/queryoutput_", idx, ".csv") 0: .h.cd flip cell each flip 0! res;
  }

timed: {[s] t0: .z.p; r: value s; (`long$ .z.p - t0; r)}

run: {[row]
  idx: string row`idx;
  q: trim row`query;
  r: @[timed; q; {(0Nj; `$"ERR ", x)}];
  r: @[timed; q; {(0Nj; `$"ERR ", x)}];
  r2: r;
  r: @[timed; q; {(0Nj; `$"ERR ", x)}];
  res: r 1;
  s: $[-11h = type res; ("error"; string res);
       @[{persist . x; ("success"; "")}; (res; idx); {("writefail"; x)}]];
  -1 idx, "|", s[0], "|", s 1;
  "|" sv (idx; s 0; string r2 0; string r 0)
  }

queries: ("J***"; enlist "|") 0: hsym `$queryFile
stats: run each queries
(hsym `$outDir, "/timings.psv") 0: (enlist "idx|status|run2timeNS|run3timeNS"), stats
exit 0
