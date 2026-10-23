// Runs src/compareOutput.q on a q implementation without the KDB-X module
// system: `use`kx.log` is the one thing it needs from it.
use: {[m] if[not m ~ `kx.log; '"use: no module ", string m];
  (enlist `createLog)!enlist {[x] `info`warn`error!({-1 raze x}; {-1 raze x}; {-2 raze x})}}
\l src/compareOutput.q
