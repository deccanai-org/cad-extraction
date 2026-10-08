# Adversarial review, round 2: step-verify-big (step_verify_big.py 2026-10-02b + integration)

Reviewed 2026-10-02 ~02:50-05:00Z against the live state (index 02:51Z, kits in `_control/z3conv/{grade,final,ifc,coord}`).

**Verdict: REFUTED as delivered.**
- **What holds.** The streamed read-back core is confirmed on new cases. Per root it matches full reads on MAPPED_ITEM
  and open-shell STEPs at 2-24 MB chunks, on a live 1.10 GB DB1 final-pass STEP, and across hosts.
- **What does not hold:**
  - The class-1 outcome. **0** models are lifted now, not 2.
  - The status claims. The patches are live and the final pass is released.
  - The integration instructions. The sync would overwrite fleet records.
  - "exact step_check output". Far-coordinate STEPs grade differently, measured on a real 1.17 GB flagged STEP.
- **Live regression.** The live grader patch turns any step_verify_big failure, including every assembly STEP (rc 2 by
  design), into class 3. The stream's own test never exercised that path.

All heavy work ran on BOX-A (i-0c694360a18d7759f) at nice 10, at most ~14 threads. The Mac only edited small files, copied
small JSON and ran sub-second Python on the 4 MB index and small parts files.
- Job package: `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big-review2/`
  (job.sh, job2.sh, job3.sh, cmp.py, cand_scan.py, resolve.py, far_copy.py, far_verdict.py, nauo_live.py, stale_check.py,
  predict_seeded.py, stub_convfleet.py)
- Results: `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big-review2/`
- Kits used (live, md5 prefix): step_check 3f26ca81, step_verify_big 0778baee, final/worker.py ad14a58c
  (`z3-grade-2026-10-01c+svb`), coord/build_index.py 41593138 (copied at 03:04Z).
- Round-1 results (same reviewer slot, earlier): `.../agentwork/step-verify-big-review/`.

## 1. REFUTED: "Two models move from class 2 to class 1 so far (1924e526, e21b8fa4)"

As of the 02:51Z index and the 49 records now in agentwork `final/results/`, the stream's records lift **0** models.
- **1924e526.** The stream's `box/predict_class.py` calls `classify_ifc` without the setup `build_index.once()` does first:
  `OPEN_SEED` and `KERNEL_SEED` are never loaded. With them loaded, as once() does (`predict_seeded.py`, live
  coord/build_index.py md5 41593138), 1924e526 stays **class 2**. It keeps `openings_volume_unverified:553` and the stand-in
  `v6_L1_tessellated_analytic` (29 parts, approx), and no read-back can clear either. The live index row says the same:
  `['not_read_back_large_file', 'per_part_verification_pending', 'openings_volume_unverified:553']` plus that stand-in.
  Round 1 confirmed the record itself: a full step_check of the 1.09 GB STEP matches the stream's record on 34,893/34,893
  roots. So the read-back is right, but the class claim is not.
- **e21b8fa4.** It is class 1 now, but not because of this stream. The IFC re-run re-converted it
  (`...e21b8fa4...v611.step`, 404 MB, `graded_by: occ_readback`, a normal read-back below RB_MAX). The stream's record is for
  the old reused 978 MB STEP (`ec1823029938..._38372854.stp`), so it is now stale and the live `apply_final` guard skips
  it. Round 1 also confirmed this record against a full read (48,515/48,515 identical).
- **Seeded prediction over all 49 current records** (`predict_seeded.json`): seeded lifted_to_1 = `[]`. Unseeded (the
  stream's method) = `[1924e526]`. Of the 43 records still current, all are class 2 after the overlay. The blockers on those
  43: parts_without_solid 38, non_positive_volume_solids 33, invalid_solids 32, openings_not_applied 23,
  parts_outside_volume_tolerance 7, v6 stand-ins 6+5+3+3+1, openings_volume_unverified 5, roots_not_transferred 2.
- **Phase 4's "17 class-1 candidates first".** 13 of the 17 are done and 0 became class 1. All 13 have blockers the
  read-back revealed or that were already there. The other 4 (2.48-2.53 GB) are still queued.
- Other numbers in the deliverable that no longer match the live index:
  - 1093cfd9 and b9e5ef0a are class 2 (`openings_not_applied:1838` / `:2549`), so the guard did not "prevent 2 wrongful
    class-1 downgrades".
  - F1 83264a1d carries `openings_not_applied:1184`, so "no other defect" is wrong.

## 2. REFUTED: integration status and instructions are stale, and step 2 now destroys data

- **"none is applied" / "Release the final pass" are false.**
  - Live `grade/worker.py` and `final/worker.py` are byte-identical to `integration/grade/worker.py` (md5 ad14a58c,
    `z3-grade-2026-10-01c+svb`).
  - Live `ifc/worker.py` has `svb_check`, and its owner has since added a converter-read-back fallback.
  - Live `coord/build_index.py` has the step_key guard in `apply_final` and the suffix-aware `detail_keys`.
  - `final/auto_status.json` says `final_hold: false`. The final pass is running: 212 IFC and 4 DB1 readback jobs.
    Fleet readback records are already landing in `_state/conv/final/results/`: 19febed2 (2.38 GB), d7a5431a (1.41 GB) and
    3ce3f88f (3.49 GB) via step_verify_big, plus 68648146, 8d578c5b and 96959781 via a full step_check.
- **Integration step 2 (`aws s3 sync agentwork/.../final/results/ -> _state/conv/final/results/`, and the same for
  detail/) would now overwrite fleet records.**
  - 2 of the 49 names already exist there from the fleet: 68648146 and d7a5431a.
  - The fleet's 68648146 record is a full step_check with a render (`render_ink 0.1652`, render_key). The stream's is
    render-less, so the sync would drop the render.
  - It would also overwrite the fleet's `final/detail/*.step_parts.jsonl.gz`, which use the same key names.
- **Stale records have moved since the split.** 6 of the 49 records in agentwork `final/results/` (not `final_stale/`) are
  stale now: 54af551c, b25ca235, b76a3588 and e21b8fa4 (all class 1 now via .v611), plus 88ff6119 and beda1382. The live
  guard skips them, but the "copy final/results, never final_stale" instruction no longer separates good records from bad.

## 3. REGRESSION (live code): any step_verify_big failure becomes class 3 in the grade/final worker

- **Code.** `streamed_check()` in live `final/worker.py` = `grade/worker.py` (md5 ad14a58c) loads the JSON only when
  rc == 0. Otherwise it returns `{'error': 'read-back rc N', 'streamed': True}`.
  - `build_index.step_checks` maps a dict with no read_status, no `skipped` and rc != -9 to `reasons += ['step_read_failed']`,
    which is **class 3**.
  - Pre-patch, the same two paths gave class 2: `not_read_back_large_file` (≥ RB_MAX, text-only) and
    `not_read_back_out_of_memory` (killed twice).
- **step_verify_big exits rc 2 by design** on any STEP with NEXT_ASSEMBLY_USAGE_OCCURRENCE (`skipped: ... assembly
  structures`). The worker throws that JSON away.
- **Reproduced with the LIVE final kit on a different real STEP than round 1** (`nauo_live.json`). The file is DB1 reused
  `MAG_GRINDING_CIRCUIT.step` (101 MB, NAUO x1534); stub S3/fleet; live `build_index.step_checks` and rules.json:
  - ≥ RB_MAX path: calls `[step_verify_big.py]` and returns `{"error": "read-back rc 2", "rc": 2}`. Verdict:
    `reasons ['step_read_failed']`, i.e. class 3. Pre-patch: `issues ['not_read_back_large_file']`.
  - Killed-twice path: calls `[step_check.py, step_check.py, step_verify_big.py]`, then rc 2 and `step_read_failed`, i.e.
    class 3. Pre-patch: `not_read_back_out_of_memory`.
- **Reachability.**
  - Latent for the current final job list. The 4 DB1 readback STEPs (1.92, 1.91, 1.52 and 1.10 GB) have NAUO 0 and
    MAPPED_ITEM 0 (deployed step_check text pass on BOX-A, `db1text_*.json`). Round 1's scan found NAUO in none of the
    flagged IFC rows.
  - Live paths that hit it:
    1. `final_jobs()` has an SDS2 branch that sends SDS2 rows tagged not_read_back_* to a readback job, and
       `final_job()` runs `check_step` for every readback regardless of pipeline. All SDS2 STEPs are assemblies, so each one
       would become class 3.
    2. Any reused NAUO STEP (23 DB1 STEPs, up to 780 MB) memory-killed twice in a grade re-run.
    3. Any other non-zero svb exit (exception, timeout rc 124) on a ≥ 1 GB file. Pre-patch these were class 2.
  - The stream's offline test (`itest_box.log`) only exercised rc 0.
- **Fix.** On rc != 0, fall back to the pre-patch result: run `step_check.py --no-occ`, set `skipped`, or keep
  `not_read_back_out_of_memory` on rc -9. Or load the svb JSON when it has `skipped`. Never return a bare `error`.
  (ifc/worker.py's owner has added a converter-read-back fallback, but without verify_parts it still ends in `readback_fail`.)

## 4. QUALIFIED: "Output is step_check.py's exact JSON". Far-coordinate STEPs get a different grade

- **Gap.** The deployed step_check.py (3f26ca81) reads far-from-origin files (coordinates ≥ 1e7 mm, no MAPPED_ITEM) from a
  copy rigidly shifted by whole km, because OCC's 1e-7 mm tolerances fail BRepCheck there. step_verify_big 2026-10-02b does
  not do this.
- **Real flagged STEP, ≥ 1 GB.** 54af551c's reused STEP `6d396deb..._66435055.stp` (1,173,917,680 B, bbox at 289 km /
  126 km, 2,099,192 far points, MAPPED_ITEM 0), `FAR_cmp.json` / `FAR_verdict.json`:

  | read of the same file on BOX-A | solids | invalid | non-positive vol | live step_checks issues |
  |---|---|---|---|---|
  | deployed step_check (full, translated by 289000000 / 125000000 / -1000000 mm) | 26,609 | 1,579 | 3,071 | invalid_solids:1579, non_positive_volume_solids:3071 |
  | step_verify_big as deployed (mine; the stream's stored record is identical) | 26,567 | 1,617 | 3,588 | invalid_solids:1617, non_positive_volume_solids:3588 |
  | step_verify_big on step_check's translated copy (`far_copy.py`) | 26,609 | 1,579 | 3,071 | same as step_check |

  - As deployed, step_verify_big differs from the grader's read on **21,086 of 24,262 roots** (volume), and on **365 roots**
    in solids and validity: +38 invalid, +517 non-positive, −42 solids.
  - Fed the translated copy, it equals the full read on **all 24,262 roots in every field except bbox**. So the streaming is
    exact, and the whole difference is the missing translation.
- **Class-1 impact shown on a small far file.** 9d37129f (`.v611.step`, at −1.457e9 / 3.036e9 mm):
  - step_check: 183/183 valid, no issues.
  - step_verify_big: 182 valid, 1 invalid (GlobalId 3jbK$ocTjEBAOkftJ_QKSw, 'c33_9'), giving `invalid_solids:1`, which
    blocks class 1 (`invalid_solids_allowed_class1 = 0`).
  - Two other far files gave equal validity but different volumes: aa1e8467 on 677/683 roots, c8689f1b on 4855/4917.
  - `far_points` / `translated_for_check_mm` are never emitted, so `step_checks` never records `far_translated_check`.
- **Reach.** step_verify_big only grades ≥ RB_MAX files or files killed twice. 54af551c's old STEP was in the stream's phase-4
  set (since superseded by .v611). Nobody has checked the other 158 ≥ 1 GiB final-pass STEPs for far coordinates.
- **Fix.** Port step_check's scan-pass detection and its per-statement CARTESIAN_POINT shift into the chunk writer, and
  emit `far_points` / `translated_for_check_mm` with bbox offsets added back. The test above shows the shifted input then
  reproduces step_check exactly.

## 5. CONFIRMED: streamed read-back equals a full read on structures and pipelines the stream never tested

The stream's 110 run records all have MAPPED_ITEM 0 and are all IFC FACETED_BREP files. I ran new cases with the live kit
on BOX-A, full deployed step_check `--max-check 1e9` as the reference, compared per root on pid, name, desc, solids,
shells, faces, bbox, valid, volume, empty and nonfinite (`cmp.py`):

| case | structure | full read | step_verify_big | per-root result |
|---|---|---|---|---|
| MA efd8f6f7 `.v610.step` 314 MB (class 1) | MAPPED_ITEM 15,201; 6,551 B-reps → 91,964 solids | 15 min, 4.8 GB | 24 MB (13 chunks) and **2 MB (145 chunks)** | **20,384/20,384 identical**, top-level identical; the grader's stored parts identical too |
| MB bb977cfc `.v610.step` 545 MB | MAPPED_ITEM 38,338, OPEN_SHELL 1,393, SBSM 95; 21 invalid | 40 min, 8.3 GB | 24 MB (22 chunks, 10 min, 0.7 GB) and **4 MB (124 chunks)** | **51,428/51,428 identical**; grader parts identical |
| DB 148a5d48 `.l.stp` 1.10 GB (**live final-pass DB1 job**, DB1 writer) | flat FACETED_BREP, 121 approx products | 40 min, 16.3 GB | as the fleet runs it: 4 workers, 8 GB budget (44 chunks, 9.3 min, tree 2.1 GB) | **29,628/29,628 identical**, top-level identical |
| MC f17e9439 `.v61.step` 1.46 GB (**live final-pass job**, MAPPED_ITEM 3,450) | 159,948 roots | still running at 05:00Z (>110 min, 12 GB RSS) | as the fleet runs it: 58 chunks, tree 2.0 GB; top-level **identical to the stream's stored record** | pending. The job keeps running and writes `MC_cmp.json` (full vs streamed, per root) to the results dir when it ends |

Cross-host check against the fleet's own final pass:
- **68648146.** Fleet full step_check (ip-10-0-102-87, with render) vs the stream's BOX-A streamed record: 6,969/6,969 roots
  identical.
- **d7a5431a (1.41 GB).** Fleet step_verify_big vs the stream's: 19,616/19,681 identical. All 65 differing roots carry
  healed tolerance > 0.1 mm (e.g. d19595: fleet 1 solid, invalid, −3361 mm³; BOX-A 2 solids, 1 valid, +3395 mm³). Top
  level: solids 28,079 vs 28,088, nonpos 3,879 vs 3,888, invalid 1,064 both.
  - This is the OCC healing non-determinism the stream documents, but it is 65 roots, not "a few solids". Two read-backs
    of the same file can give different issue counts.

Other confirmations:
- My step_verify_big rerun of the 1.17 GB far file reproduced the stream's record exactly, at top level and on all 24,262 roots.
- Round 1 (`step-verify-big-review/`): full reads of e21b8fa4 (978 MB) and 1924e526 (1.09 GB) matched the stream's
  records on 48,515 and 34,893 roots.
- **Full read impossible, streamed works.** 0b3b8b2f's 1.21 GB STEP, where the stream's record has 4 crashed roots
  (3 × rc −11, 1 × `read fail:3`):
  - A full deployed step_check **segfaulted** (signal 11 after 40 min, 15.9 GB RSS, no output).
  - The streamed result (roots_not_transferred:4, class 2) is strictly more information than a full read could give.
  - Small caveat: one crashed chunk held 3 products (10681-10683), so 2 innocent products, a wall and a curtain panel, are
    also reported as crashed.

## 6. Smaller issues

- **Final-pass memory reservation.** `final/worker.py` creates `Fleet('final', ..., lambda j: max(8 GB, step_bytes*60,
  size*20))`, and no `_state/conv/final/mem_buckets.json` exists to replace it.
  - The `need_bytes` fix in the patch applies only to the grade fleet. The 163 ≥ 1 GiB readback jobs therefore reserve a
    median 128 GB each, up to the 0.8 × host cap of 396 GB; streamed peak trees measured here are 2-6 GB.
  - Correctness is fine, but it throttles "finish ASAP".
- **Streamed records carry no render.** They skip the `blank_render` check that class 1 otherwise gets.
- **Not part of `complete`.** `streamed.complete` ignores `pd_not_reported_as_root` and `dangling_refs`, and build_index
  never reads `complete`. All are 0 on every record checked.
- **Integration test coverage.** `test_check_step.py` only covered rc 0. That is why section 3 was missed.

## What must change before this is "ready"

1. Report 0 current lifts. 1924e526 is blocked by openings / stand-in, and e21b8fa4 is now class 1 from its .v611
   re-conversion. Fix predict_class.py to load OPEN_SEED / KERNEL_SEED as `once()` does.
2. Add an rc != 0 fallback in `streamed_check` (grade/final worker): text-only plus `skipped`, or keep
   `not_read_back_out_of_memory` on −9. Then no assembly STEP or svb failure turns a class-2 model into class 3.
3. Port the far-coordinate translation, or stop claiming exact step_check output.
4. Rewrite the integration section:
   - The patches are live and the final pass is released.
   - Do NOT `aws s3 sync` over `_state/conv/final/{results,detail}/`. Copy only ids with no fleet record, and only
     records whose step_key equals the live index step_key.
   - Re-split stale records: 6 more are stale now.
5. Set a final-pass memory rule for streamed jobs, e.g. `SVB_MEM_GB + 1` for step_bytes ≥ RB_MAX, as the grade fleet has.
