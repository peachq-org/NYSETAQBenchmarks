/ Derives query parameters FROM the loaded sample data.  The sets shipped under
/ artifacts/parameters/test name instruments absent from external/kx/taq/testdata,
/ so every parameterised query returns nothing there and proves nothing.
/ Only the frequency ORDERING is upstream's (artifacts/parameters/genParameters.q:
/ most-traded, then the 20th-percentile instrument).  The set SIZES are not: the
/ sample holds four instruments, so there is nothing to sample down to 50 or pad
/ out to 1000, and upstream's random draw becomes taking them all.

system "l ", getenv[`OPENQ_DIR], "/taq.q"
paramDir: taqEnv[`TAQ_PARAMS; taqRoot, "/openq/params"]

symFreq: exec sym from `cnt xasc 0!select cnt: count i by sym from quote
absent: `ZZZZ                     / an instrument in no table: the empty-filter arm

freqInstr: last symFreq
infreqInstr: symFreq floor 0.2 * count symFreq
fiftyInstrs: symFreq, absent
thousandInfreqInstrs: symFreq[til (count symFreq) div 2], absent

put: {[f; lines] (hsym `$paramDir, "/", f) 0: lines}
put["freqInstr.txt"; enlist string freqInstr]
put["infreqInstr.txt"; enlist string infreqInstr]
put["fiftyInstrs.txt"; string fiftyInstrs]
put["thousandInfreqInstrs.txt"; string thousandInfreqInstrs]
put["datadate.txt"; enlist "2025-07-01"]
put["timeBuckets.txt"; ("closed=0D00:00:00.000"; "preopen=0D04:00:00.000";
  "open=0D09:00:00.000"; "morning=0D09:30:00.000"; "afternoon=0D12:00:00.000";
  "afterhours=0D16:00:00.000"; "maintenance=0D20:00:00.000")]

-1 "freqInstr=", string[freqInstr], " infreqInstr=", string infreqInstr;
-1 "fiftyInstrs=", "," sv string fiftyInstrs;
-1 "thousandInfreqInstrs=", "," sv string thousandInfreqInstrs;
exit 0
