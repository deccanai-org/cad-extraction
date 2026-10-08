# Adversarial review: coverage-regression

Reviewed 2026-10-02 00:45-01:10Z. Verdict: **CONFIRMED WITH CAVEATS**.

The diagnosis holds up under independent checks, and three of the four patches are correct. However:
- The packaged "kit_j_patched" deploy set is stale: code k landed at 00:20Z and code l at 00:23Z.
- The worker best-of fix introduces a new record/STEP mismatch case.
- The DB1 best-of rule trusts coverage numbers that were never verified.

## Where the work ran (nothing heavy ran on the Mac)

- BOX-B (i-076e73980707c7dbe) was at load 106 with only 28 GB of memory available. Only the light jobs ran there: the index replays and the worker unit test.
- The decodes, full conversions and OCC read-backs ran on BOX-A (i-0c694360a18d7759f, 415 GB free, load ~45). This is an existing box; no instances were launched. Each job stayed at 16 threads or fewer.
- Scripts: `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/coverage-regression-review/`
- Results: `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/coverage-regression-review/`, in the folders `sim/`, `wcheck/`, `ab/` and `wtest/`.
- Box work dirs were cleaned afterwards; only scripts and logs remain.

## What was re-checked, and on which different cases

### 1. The index replay is faithful
- `sim_review.py` replays `once()` for DB1 with the deployed 00:44Z `build_index.py`. It runs `rejoin_grades`, `apply_final` and best-of, and all S3 writes are blocked.
- Against the production index of 00:57Z it matches on 105 of 106 rows (class and step_key).
- The one mismatch is 2fdaa7dae6e4: its result moved from j to l between the index build and the replay.

### 2. Patched build_index on a later snapshot (`sim_pair.py`)
- Both indexers ran on one snapshot of the live state, taken at 01:00Z. The agent's own replay used the 00:20Z state.
- The patch applies cleanly to the current 00:44Z `build_index.py`, with all anchors found.
- Stock gives {2:100, 3:6}; patched gives {2:97, 3:9}. 88 of 106 rows are unchanged.
- The best-of switches are exactly the claimed 11: 2915, 3c6b, 4518, 5b33, 6b87, 7c82, 7d7b, 8ebd, c8d7, ea1a, fd30.
- 97c7, b3d4 and f082 go from class 2 to class 3, with true member coverage 0.0.
- The 6 Windows class-3 rows change their reason from part_coverage to member_coverage_0.00.
- No grader loosening:
  - The class thresholds are untouched.
  - All Windows rows now sit below the 0.5 member threshold.
  - The manifest issue moved to `issues_info` only on rows that are class 3 anyway, or that carry `bolt_solid_no_hole` stand-ins.

### 3. Windows STEPs, checked by a different method (`wcheck.py`)
- **Entity histogram** (6eab, 3c6b, 97c7, 8ebd, d6f8, 7d7b, 6b87):
  - The only solids are MANIFOLD_SOLID_BREP, and their count equals CLOSED_SHELL.
  - There are no SHELL_BASED_SURFACE_MODEL, extruded, mapped or tessellated items that the text join could miss.
  - The PRODUCT count equals the schedule rows with solids, plus 1 root.
- **OCC XCAF read** (8ebd, d6f8, 7d7b, 3c6b, 6b87): every product label was read independently of the text parser.
  - 0 ids appear in only one of the two reads.
  - OCC member coverage equals the text join: 0.0 / 0.0 / 0.0 / 0.1062 / 0.1498, against text 0.0 / 0.0 / 0.0 / 0.1061 / 0.1497.
  - On 3c6b, OCC sees fewer ids with a solid than the text join (1607 vs 1848), and fewer solids (7170 vs 7411). So the text join is the generous one; that changes nothing here.
- **Schedule cross-check, 6eabb07e7145** (not one of the agent's examples). Of the 231 decoder members:
  - 168 are not listed by the Windows reader at all: W14X48 23, W14X43 19, C8X13.7 16, ...
  - 61 are listed on the straight path with no solid.
  - 2 are listed on the plate path with no solid.
- **Agent's aggregate**: 404 of 129,697 members; connections 64,106 of 170,996. Both reproduced from its wj files.
- Small wording error: the 52,083 "listed, no solid" members are 50,909 straight plus 1,174 plate, not "every straight".
- 8ebd's own Windows `conversion_report.txt` says "solids that failed: 105". These are C200*90*8, L65X65X6 and other straight members.

### 4. db1bolts guard, on the deployed code l kit (not i/j as in the agent's runs)
- **Stock l crashes**: `convert_error` (KeyError 's') on 7c68, 3585 and 48e0. Production 3585 also failed under code k and kept its h STEP.
- **bolt_catalog.json**: all 14 catalog models have 9-16 `{'ambiguous': n}` sizes. Only the 3 models that use one of those sizes crash.
- **New controls** (not used by the agent): 172f, 39a8, 575d, 5a22, 6872, ddc8. Decoding with l and with l+guard gives identical parts lists (GUID column ignored) and identical IFCs (GUIDs and timestamps masked).
  - 39a8 full run: identical on both kits (1588 solids, 50 approx, 14,362,737 bytes).
- **7c68 full run on l+guard**: 7,841 solids, all valid, 1593/1593 members, 0 of 1,835 parts outside 5% volume, 75.6 MB.
- **48e0 full run on l+guard**: 8,692 solids, 0 invalid, 1184/1184 members, 833 approx parts. The production h STEP has 529 approx parts, so worker best-of keeps h, as the agent predicted.
- No geometry is invented: the fallback is the existing `standard_geometry` path (Tekla harvest, then tables).
- Possible refinement: keep the catalog nut and washer and fall back only for the head.

### 5. Overlay extension, on the code l kit
The 5 new per_model entries:
- The R.B Ø20 entry is CIRC dims [10.0], which is a radius: the base catalog stores ROD1" as 12.7. It matches the existing R.B Ø20 entries for 14e4, 172f, 33f2 and others.
- The angle entries equal the global overlay.
- The base is unchanged (only the meta and the new per_model keys differ).

Decoded members on code l, without the extension -> with it:
- cc9b: 93 -> 163
- 4fa8: 121 -> 180
- 77d1: 228 -> 258

All the added R.B Ø20 parts come out as `written/catalog`.

### 6. Other checks
- **Timeline**: history.json confirms the class counts the agent quoted: before g {2:59, None:45}, before h {2:61, None:43, 3:2}.
- **Data-3 member share across codes**: 34 models went up, 0 went down, and 7c68 crashed (agent's snapshots db1res -> db1res3).

## Problems found

1. **The kit_j_patched deploy set is stale and would regress production if followed literally.**
   - Deployed is now code l (00:23Z): the k Tekla-improver bolts (db1bolts2, Tekla harvest), the ifc_unhole crash fallback, MAPPED_ITEM, and VSUF `.l`.
   - Integration step 2 says to copy `kit_j_patched/{db1bolts.py, worker.py}` and bump CODE "e.g. ...k". That would:
     - set CODE back to `z3-db1-2026-10-01j` and VSUF back to `.j`;
     - remove db1bolts2 and ifc_unhole;
     - reuse a code letter (k) that has already been deployed.
   - What to do instead:
     - Apply the anchored patches to l. Verified: `apply_worker_bestof_fix.py` and the db1bolts guard anchor both apply to l.
     - Copy only the overlay, whose base equals l's overlay.
     - Bump to code m.
2. **The worker best-of fix creates a new inconsistency.**
   - `_process_inner` uploads the STEP, check.json, png and census detail to the versioned key `<jid><VSUF>.stp` before the best-of decision.
   - With the fix, take a same-code duplicate run that finishes ok but scores worse (one more invalid or approx part). The fleet keeps the earlier record, but the file at its step key is now the new, worse STEP.
   - The `wtest.py` unit test on the l worker shows this (case S2):
     - Fixed worker: it returns runA's record (0 invalid, 5 approx), while the file at the key comes from runB.
     - Stock worker: it returns runB's record, which matches the file.
   - The claimed case (a duplicate run that crashes, S1) is fixed correctly.
   - Suggested condition: keep prev only if `new` did not upload to prev's step key. That is, if `(prev.get('step') or {}).get('key') == new.get('out_key')` and new is ok, return new.
3. **best_of_db1 compares coverage of different provenance.**
   - 5b33: it picks the code-i STEP, whose issues include `not_read_back_large_file` and `step_vs_decoder_join_unavailable`. Its member coverage of 0.9839 and all-parts coverage of 1.0921 are decoder counts, not a STEP join.
   - It drops the disk-1/2 STEP, whose coverage of 0.7468 was verified by a join.
   - The class is 2 either way, but "0.7468 -> 0.9839" is not a verified gain.
   - Suggestion: only let coverage decide when both sides have a real join; otherwise fall back to the stock rule.
4. **Fragile input.**
   - The patched production `build_index` reads WJ results from an agent scratch path (`_state/agentwork/coverage-regression/wj/`).
   - If that path is cleaned up, the Windows rows silently fall back to the manifest ratio, and 10 STEPs with no members go back to class 2.
   - Move the results under `_state/conv/grade/windows_join/` before deploying.
5. **Minor.**
   - "every straight member" should read 50,909 straight + 1,174 plate.
   - The best-of note says "graded worse than <same code>" when prev carries the same code.
   - 3585 and 48e0 will keep their h STEPs (approx 530/529 vs 833), so the bolt fix only changes the outcome for 7c68.

## Regression risk
- Grading: low. The build_index patch only tightens grading, it touches DB1 only, and the replay shows 88 of 106 rows unchanged.
- db1bolts guard: none for models that do not crash (6 new controls identical).
- High if the stale kit_j files are copied (problem 1).
- Moderate edge case from the worker fix (problem 2).
