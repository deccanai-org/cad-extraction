# Adversarial review of audit-sds2-v5x (SDS2 v5.1/v5.2/v5.3 regression audit + fleet patches)

Reviewer run: 2026-10-02 00:34-00:44Z on BOX-C i-0d97427e58ca5ef28. All heavy work ran on the box; the Mac only did small file
reads and diffs. Fleet state was only read, and every repair_state run was a dry run (no `--apply`).
- Box job inputs: s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-v5x-review/ (main.sh, main2.sh, rvtests.py,
  rvcheck.py, rvsteps.py, rvpairs.py, rvmore.py, t2/ = current deployed kit + the audit's .patch applied)
- Outputs: s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-v5x-review/ (progress.txt, t1/, t2/,
  aud/out/ = the audit's own audit5x.py re-run at 00:36Z, rvcheck.json, rvsteps.json, rvpairs.json, rvmore.json, rp/dry_*.txt, more/)
- Box dir /work/agentwork/audit-sds2-v5x-review removed afterwards. No processes left running.

Verdict: **confirmed_with_caveats**. The fleet-runtime regressions, the repair dry run and the best-of-noise cases all reproduce on live
state. One headline claim is refuted ("no converter-level regression"). worker.patch has a latent data-integrity defect, and
convfleet.patch has side effects. Fix both before deploying.

## Reproduced (holds)
| claim | re-check (live S3 / logs at 00:36Z) |
|---|---|
| 3 v5.1 results overwritten by v5.3 out_of_memory | ff442ef1, bee88c67 and 556b8979 are still `fail/out_of_memory`, code v5.3, kills=5. Kill lines (my own grep): ff442ef1 0,0,0,2,2 GB; bee88c67 0x5; 556b8979 0x5. All are v5.3 on z3-convfleet-v1 'largest on host'. The v5.1 outputs are published (job.json published=true; STEPs 508,487,369 / 1,202,895,399 / 32,219,003 B). |
| repair restore class 3 -> 2 | Dry run on the box at 00:36Z gives 3 -> 2 for all three, with both the original plan and a fresh plan. |
| 5 false OOM verdicts | Kill RSS exactly as claimed (CLAYTON 0x5 twice; a80e86db 0,0,2,1,3; IKEA 1,7,5,0,7; PERCEPTIVE 4,6,0,6,0). The fresh plan adds a 6th: 8a6cfce3 NORTH HAVEN MS_JOB, 6,2,0,7,0. |
| VOID / 401 kept old on noise | Grep on the box: VOID v4 STEP has 0 `[approx` lines vs 34 in v5.1, same 25 MANIFOLD_SOLID_BREP. 401 CONGRESS v4 has 0 vs 4, same 3,934 MSB. |
| SHERIFFS v5.3 = 4 more duplicates | pieces.csv diff: exactly 4 pieces gone (PL1 1/2x7 1/4, piece 6788, MISC 1893-1896), now `also_on_member` 1888-1891. Manifest: bolts_nominal 741->737, solids_written 6908->6900. Read-back -16 = 4 plates + 4 bolt assemblies. A genuine de-dup. |
| v5.2->v5.3 code diff = duplicate grid only | `diff -r` of the unpacked zips: to_step2.py:979 plus CHANGES.md only. |
| watchdog kill census | My log census at 00:36Z: v5.3/v1 largest-on-host made 418 kills on 268 jobs (234 <1 GB, 147 1-8 GB, 37 >=8 GB, median 0 GB). Legacy v5.1: 368 kills, median 15 GB. v4: 240 kills, median 23 GB, last at 00:22:42Z. |
| at-risk finished jobs | Grew: 79 -> 93 at 00:36Z; reset list 90 -> 99; fleet-made OOM results 8 -> 11. The reset tool correctly skipped bce3a755, which became OOM after a real 39 GB kill. |
| tests | test_patches.py prints ALL EXPECTATIONS MET on BOX-C against both the audit's bases and the current deployed kit (convfleet 00:16:47Z, worker 00:10Z). The patches apply cleanly to the current convfleet.py, worker.py and build_index.py (00:24:18Z) with offsets only, no fuzz. |
| build_index.patch is useful | Real case, 08e69411 SYSCO_TRUCK: the deployed rule keeps the reused STEP (10,067 solids, score (2,7)) over the fresh v5.3 (11,842 solids, score (2,8)). The patched rule picks the fresh one. |

## Refuted / problems
1. **"No converter-level regression; solids lower only by removed duplicates" is false.**
   - Job fb1cae548c94fba2897db015 (19002-IMS6_JOB, 7.720). All three labels finished `ok_stage1` (stage2 missing_job_file):
     - v5.1: 8,540 placed solids, 3,333 unique, 995.8 t.
     - v5.2 and v5.3: 4,652 placed solids, 3,283 unique, 988.7 t.
   - stage1_members.csv diff: 50 JOIST members (52DSLH, ids 3014-...) went from `solid=1 derived_from_designation open-web joist` in
     v5.1 to `solid=0 joist envelope box (no chord data)`. Those 50 joists are no longer in the STEP, and skipped stays 0, so nothing
     reports the loss.
   - Best-of gives every ok_stage1 the same estimate (2.5,0,0,0), so the newer output won the tie. The index now publishes the v5.3
     stage-1 STEP without the 50 joists (class 2 C either way).
   - The audit had this job in per_job.csv, with three outputs, but left the stage-1 solids blank. The drop was invisible to it.
   - worker.patch ("ties go to the newer label") reinforces this.
   - Likely cause: v5.2's joist-depth-from-designation change (joist.py), followed by the stage-1 envelope fallback, which writes no solid.
2. **worker.patch: latent result/STEP mismatch on same-label re-runs.**
   - All outputs of one label go to `<id>/<label>/`, and `_process` uploads the STEP, job.json and manifest before best-of runs.
   - Removing the same-label shortcut means a same-label re-run that grades worse keeps the old record, while the files at its step key
     now come from the new run. A same-label re-run happens through a redo_ids entry with this code (the documented hot-fix path) or
     CONV_RERUN.
   - rvtests W: the stored record says 1,000 solids, but the STEP at that key is the re-run's 990-solid file.
   - Fix: compare only when `prev.converter.label != LABEL`.
3. **convfleet.patch side effects** (rvtests on the current deployed kit):
   - R3: an uncounted emergency kill sets `pm=0`, which throws away an earlier counted kill's reservation (48 GB -> 17 GB).
   - R4: existing deferred records have no `kills_by_code`, so earlier real kills are forgotten (4 real kills -> 5 more allowed). Old
     unpatched writers drop the field again on every write.
   - R1 (registry branch): if the chosen victim is below kill_min, nothing is killed until MemAvailable < 2% (9.9 GB). The larger job is
     never chosen. The log line says "largest elsewhere on host 0GB", which is misleading.
   - R2 (legacy branch): if the largest process is a non-fleet process, nothing is killed even at 1% available, so the kernel OOM killer
     decides. The deployed code would kill its own 6 GB job.
4. **Stale "patched .py" files.**
   - fixes/convfleet.py (62,432 B) was built on a 56,156-B base that lacks the lead's 00:16:47Z mem_tabs change.
   - fixes/build_index.py lacks the 00:24Z unholed_elements / expected_gb changes.
   - Deploying those files instead of the .patch would revert the lead's work.
   - base_sha256.txt says the base is the 56,774-B file, but base/convfleet.py is 56,156 B.
5. **best_key rounds into buckets rather than applying a tolerance.** 1.0051 vs 1.0049 (0.0002 apart) still decides and keeps the old
   output. The "differences below 0.01 are ties" claim is not exact.
6. **Numbers have drifted.**
   - jobs_reconvert.json now holds 3 entries (rewritten 00:37:55Z), not 597. 759 reuse contents, of which 1 has a fresh result.
   - z3-convfleet-v2 is no longer at "0 kills": since 00:18Z, v5.4 made 25 largest-on-host kills (15 at 1-8 GB) and v5.3 made 8. The
     registry-branch "over reservation" rule made 10 kills at 0-6 GB on jobs with 21-59 GB reservations (ip-10-0-102-136). The patch
     would spare the ones under 4.95 GB.
7. **Overstated framing.**
   - Two of the three "good" restored results, P-01 and l-arch, are 1-solid R-corpus reference models with pieces_not_built 834 and
     25,305. v5.2+ writes open reference shells for models like these, so a v5.3 re-run under a patched fleet is the real fix.
   - "v5.3 peak RSS lower than v5.1" is subject to survivorship bias (v5.3 jobs were killed far more often) and was not verified.

## Recommendation
- Apply `repair_state --only reset` now. Restore and reopen are OK after convfleet is fixed.
- Before deploying:
  - Fix worker.patch so it skips the comparison for the same label.
  - Fix convfleet.patch so it keeps `pm` and seeds `kills_by_code` from `kills` for legacy records. In the registry branch, choose the
    next victim at or above kill_min instead of sparing.
- Deploy the .patch files, never the stale full files.
- Add a stage-1 solids/members comparison to best-of. Investigate fb1cae54: the v5.1 STEP, with the 50 joists, is still under
  `<id>/v5.1/`.
