# Data-3 → STEP: bug report (running log)

Shown to Dhiren in every status update. Status values:
- **FIXED**: live and verified.
- **DEPLOYING**: in the builder's current release pass.
- **IN PROGRESS**: a fixer is on it.
- **OPEN**: no fix yet.

Last updated: 2026-10-02 01:30Z.

## Fleet / infrastructure

| # | Bug | Impact | Status |
|---|---|---|---|
| F1 | Temp STEP files from killed SDS2 jobs stayed in RAM (/tmp is RAM) | ~900 GB of RAM lost fleet-wide, more OOM kills, SDS2 ETA 13 h | FIXED 00:39Z (TMPDIR on disk, removed with the job) |
| F2 | Memory watchdog couldn't see old workers' big jobs, killed tiny jobs instead | ~50 useless kills | FIXED 00:39Z (one leader per box kills by scope) |
| F3 | Memory reservations far above real use | boxes at 15-40/64 CPU with 100-330 GB free | DEPLOYING (admission on real memory, Pass 1) |
| F4 | A fixer emptied `_control/z3conv/sds2/pybin.txt` (swapped `aws s3 cp` arguments), 01:14Z | new SDS2 workers couldn't launch for 3 min (0 actual failures found) | FIXED 01:17Z (restored); guards DEPLOYING |
| F5 | My message resumed a duplicate copy of a workflow fixer | two agents editing one folder | FIXED (duplicate stood down) |
| F6 | Old converter versions (SDS2 v5-v5.3, IFC +s6) still claimed fresh jobs | pre-fix output still produced | DEPLOYING (retire, Pass 1) |
| F7 | False out-of-memory verdicts overwrote 3 published SDS2 STEPs | 3 models wrongly class 3 | DEPLOYING (restore + failed run never replaces ok) |
| F8 | ~70 stale waiting worker processes woke with old code | load spikes, old rules | FIXED (singleton check) |
| F10 | I killed the `sleep` inside BOX-C's `( sleep; shutdown )` self-shutdown timer while trying to extend it, 17:46Z | BOX-C terminated mid-test (SDS2 v5.5.8 already shipped; SOCORRO / Spectrum checks lost) | FIXED (moved the SDS2 fixer to BOX-B; lesson saved) |
| F9 | IFC re-runs are slow (~80/h for ~3,300 models) | IFC could finish long after SDS2 | DEPLOYING (30% of SDS2 boxes for IFC re-runs) |

## Grader / classification

| # | Bug | Impact | Status |
|---|---|---|---|
| G1 | IFC holes/copes not cut, but graded class 1 (no volume check) | ~2,470 IFC models with uncut parts, ~1,200 of them shown as class 1 | DEPLOYING (openings_not_applied tag + 6.1 re-run) |
| G2 | "Best-of" picked by issue count, not coverage | kept worse STEP: IFC 90, DB1 12, SDS2 joist tie | SDS2 tie DEPLOYING; full fix Pass 2 |
| G3 | Old Windows Tekla STEPs graded from their own manifest (real coverage 0.3%) | ~10 models class 2 instead of 3 | DEPLOYING (Tekla-id join) |
| G4 | SDS2 coverage counted empty members, reference parts, removed duplicates | e.g. b244541c class 3 with all 1,264 pieces exact | DEPLOYING |
| G5 | Arithmetic: negative invalid_solids, DB1 coverage > 1, blank render alone = class 3 | wrong tags/classes on ~65 models | DEPLOYING |
| G6 | Parts open in source (closed only by healing) and tessellated analytic parts counted exact | ~80 + ~75 IFC models wrongly class 1 | Pass 2 |
| G7 | STEPs of 1 GB or more only text-checked | ~215 models not fully verified | Pass 2 (step_verify_big) |
| G8 | Automatic final pass could start before re-runs finish | would freeze known-wrong classes | DEPLOYING (final hold) |
| G9 | SDS2 re-run rules missed ~1,090 old/reused models | "fixable" labels never retried | DEPLOYING |
| G10 | Loose-folder SDS2 jobs split in two by the scan | 15 jobs → 29 incomplete halves | Pass 2 |

## Converters

| # | Pipeline | Bug | Impact | Status |
|---|---|---|---|---|
| C1 | IFC 6.1-rc | Repeated (mapped) parts invalid at some placements | invalid solids in instanced models | IN PROGRESS (6.1.1 testing) |
| C2 | IFC 6.1-rc | Memory blow-up on SDS/2 IFCs with openings | 173 GB from an 18 MB file | IN PROGRESS (patch E → 6.1.1; per-job cap DEPLOYING) |
| C3 | IFC | Read-back memory kill recorded as converter failure | 18 re-runs fell back to v5 | IN PROGRESS |
| C4 | IFC | Placement written with 10 digits | precision lost beyond 1e8 mm | IN PROGRESS (patch A → 6.1.1) |
| C5 | IFC | 2 corrupt bolt assemblies sink whole models | 2 big models class 3 | IN PROGRESS |
| C6 | IFC | CIS/2 files saved as .ifc, no reader | 2 models class 3 | OPEN |
| C7 | Tekla | Crash on ambiguous bolt-catalog entries (KeyError 's') | 3 models crash / serve old STEP | DEPLOYING (code m) |
| C8 | Tekla | Stored hole tolerance discarded | 23,897 holes at nominal size | DEPLOYING (code m) |
| C9 | Tekla | New-engine bolt stats missing keys, axis flip, grip clipped | all 7.5+ bolts graded nominal; 1,792 heads 50 mm low | DEPLOYING (code m) |
| C10 | Tekla | Beam-end cuts (fittings) not decoded | beam ends wrong, no Tekla class 1 | IN PROGRESS (decoded 501/526, applying) |
| C11 | SDS2 v5.2+ | 50 joists silently dropped (fb1cae548c94) | 3,888 solids missing | IN PROGRESS |
| C12 | SDS2 v5.x | "Absurd extent" rule drops valid bars/rebar | 5,076 pieces on 13 jobs | IN PROGRESS |
| C13 | SDS2 | Nominal bolts written on top of stored bolts | double bolts, 618 jobs exposed | IN PROGRESS |
| C14 | SDS2 | Reference models not recognised; open-shell placements dropped | ≥15 jobs class 3; 3.18 M placements | IN PROGRESS |
| C15 | SDS2 | Main-member holes partly missing (version-dependent) | hole recall 0.36-0.87 | IN PROGRESS (holes from the job's own NC1 files) |
| C16 | SDS2 | Old-version (7.x) pieces approximated | ~900 models | IN PROGRESS |
| C17 | SDS2 | Pieces not built | 388 models | IN PROGRESS |
