// Load one day of master/trade/quote and the root objects from a splayed kdb
// database, i.e. one written by src/qengine/psvToSplayed.q.
//
// src/runQueries.q's loadKDBDBIntoMemory does the same job for the
// date-partitioned kdb+ database and its shape is followed deliberately: root
// objects first, because the splayed sym columns are enumerated against the
// sym domain living there, and then each table materialised with
// `select ... where i>-1` rather than left mapped, because the benchmark times
// queries over data in memory. The layout is a directory of splayed tables
// named by date, not a kdb+ partition, so it is read by path rather than by
// loading a partitioned view.

loadRootObjects: {[db]
  {[db; f]
    p: .Q.dd[db; f];
    if[p ~ key p; f set get p]}[db] each key db;
  }

loadSplayedDataset: {[src; date]
  db: hsym `$src;
  loadRootObjects db;
  dpath: .Q.dd[db; date];
  {[dpath; tName]
    -1 "loading table ", string tName;
    tName set select from get[.Q.dd[dpath; `$string[tName], "/"]] where i>-1;
    / symbols instead of enums against the global sym vector, as src/runQueries.q does
    @[tName; where 20h=type each flip value tName; value];
    -1 "  shape of ", string[tName], ": ", string[count value tName], " x ",
      string count cols value tName;
    }[dpath] each `master`trade`quote;
  delete sym from `.;
  / exchange names as symbols, as src/runQueries.q's loadKDBDBIntoMemory leaves them
  if[`exnames in key `.; if[0h ~ type value exnames; exnames:: `$exnames]];
  }
