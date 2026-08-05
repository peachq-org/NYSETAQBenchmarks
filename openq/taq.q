/ TAQ source tables for the openq oracle harness.
/ The column names and type letters below are TRANSCRIBED from
/ external/kx/taq/taq/inputSchema.q, not read from it, so that the same three
/ tables can be stated identically here, in rundb.py's SQL, and in the fixture
/ openq vendors into its own test tree.  A schema change upstream must be
/ carried into all three by hand.
/ Row order matches the benchmark's canonical `-sortcols time` configuration.

taqEnv: {[k; d] $[count v: getenv k; v; d]}
taqRoot: taqEnv[`TAQ_ROOT; "."]
taqData: taqEnv[`TAQ_DATA; taqRoot, "/external/kx/taq/testdata"]

tradeCols: `time`ex`sym`cond`size`price`stop`corr`seq`tradeId`source`tradeReportingFacility`participantTimestamp`tradeReportingFacilityTRFTimestamp`tradeThroughExemptIndicator
quoteCols: `time`ex`sym`bid`bsize`ask`asize`cond`seq`nationalBBOIndicator`finraBBOIndicator`finraADFMpidIndicator`corr`source`retailInterestIndicator`shortSaleRestrictionIndicator`LULDBBOIndicator`SIPGeneratedMessageIdentifier`nationalBBOLULDIndicator`participantTimestamp`FINRAADFTimestamp`FINRAADFMarketParticipantQuoteIndicator`securityStatusIndicator

taqRead: {[types; names; file] names xcol (types; enlist "|") 0: hsym `$taqData, file}

trade: `time xasc taqRead["NCSSEESHIJCSNNB"; tradeCols; "/EQY_US_ALL_TRADE_20250701.psv"]
quote: `time xasc raze taqRead["NCSEIEICICCCCCCCCCCNNCC"; quoteCols] each
  ("/SPLITS_US_ALL_BBO_Y_20250701.psv"; "/SPLITS_US_ALL_BBO_Z_20250701.psv")

exnames: "ABCDIJKLMNPSTQVWXYZ" ! (
  "NYSE American"; "NASDAQ OMX BX"; "NYSE National"; "FINRA Alternative Display Facility";
  "International Securities Exchange"; "Cboe EDGA Exchange"; "Cboe EDGX Exchange";
  "Long-Term Stock Exchange"; "Chicago Stock Exchange"; "New York Stock Exchange"; "NYSE Arca";
  "Consolidated Tape System"; "NASDAQ Stock Market"; "NASDAQ Stock Exchange";
  "The Investors' Exchange"; "Chicago Broad Options Exchange";
  "NASDAQ OMX PSX"; "Cboe BYX Exchange"; "Cboe BZX Exchange")
