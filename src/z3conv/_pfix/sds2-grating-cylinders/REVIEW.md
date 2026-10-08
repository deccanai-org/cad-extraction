# Adversarial review: sds2-grating-cylinders (2026-10-02)

**Verdict: confirmed with caveats.** The claims hold up against the raw box outputs and against production fleet
runs of real models the author never touched. I found no lost parts, no new invalid solids and no class
regressions caused by the patch. Every tag it removes is backed by geometry and weight checks. The caveats are below.

## What blocked the planned box re-run
* The `annotationprod-publish` SSO session (the `annotationprod-audit` sso-session) has expired. Its refresh fails
  without an interactive login, so I could not reach BOX-C through SSM or stage anything under `agentjobs/`. I did not
  try any other credentials. The owner has to log in again before anything new can run on the box.
* What I used instead, all read-only with `AWS_PROFILE=bim` and small parse scripts on the Mac:
  1. The author's raw box outputs for v5.5.3 and v5.5.3 + patch (`agentwork/sds2-grating-cylinders/conv/{v553,v553h}`):
     manifests, `pieces.csv`, logs and `rc.txt` for all 15 jobs.
  2. **Production fleet runs of the merged code.** The patch has already shipped: v5.5.6 = v5.5.5 + the interim patch +
     an owner tagging change (`sds2_v5/sds2-step-pipeline-v5.5.7.CHANGES.md`, `STATUS_RESUME.md`). v5.5.6.1 uses the
     same zip, and v5.5.7 is the current fleet converter.
     - `rel556/557/558` `grating.py` is byte-identical to this patch's file.
     - `rel556` `to_step2.py` equals v5.5.5 + the patch, except two things: the budget test is `>` (the interim code),
       and the owner tags cut panels that were built from partition cells.
     - `conversions/sds2-step/<id>/<ver>/` keeps the previous version's outputs, so the fleet gives real
       before/after pairs on held-out models.

## Checks
| # | check | result |
|---|---|---|
| 1 | Patch applies to a clean v5.5.3 zip (sha `706e1289...c0a9` matches) | clean. The patched tree is identical to `work553/`. Also applies cleanly to `rel555`. |
| 2 | README table 4 (15 jobs, v553 vs v553h), recomputed from raw manifests | every number matches: classes, mesh_cylinder / grating stand-ins, exact pieces, skipped, read-back solids / invalid, steel ratio, wall time |
| 3 | Per-placement transitions over the 15 jobs (`review/pcmp.py`) | 0 placements lost. +182 SLC4, +2 LAREDO and +1 PSU placements that v553 had skipped. Only transitions are tagged -> untagged: 26,512 straight guess -> cap-axis cylinder, 3,041 straight guess -> exact B-rep, 3,202 grating panel -> exact grating. No exact -> tagged change and no origin moved. |
| 4 | Table 1 and rod replay totals (`data/gr4f`, `data/rod2`) | match: 540 pieces, 377 / 112 built, 3,768 / 3,782 placements; 30,708 -> 0 guesses |
| 5 | Is the cut-panel premise ("SDS2 weighs the uncut W x L stock") true, tested without using the built geometry? | **yes.** Over the 112 cut pieces, SDS2 weight / (record W x L) divided by the same-spec uncut density has median 0.997 (range 0.945-1.219; the high end is narrow strips). |
| 6 | Is the grating record decode stable? | one offset per layout: 440-B f32 @322, 902-B @360, 1024-B @364 (the README does not mention this layout), 8.0 @344. No stray matches. |
| 7 | **Held-out real models:** 20 fleet pairs v5.5.5 -> v5.5.6.1, per placement (`review/hcmp.py`, `review/held_summary.json`) | 0 lost placements; read-back invalid unchanged on every model (Eastwood 1 -> 1, already class 0); classes unchanged. Only transitions are tagged -> untagged: 1,942 rods -> own B-rep, 331 -> cap-axis cylinders, 1,037 grating panels -> exact. Failures stay tagged with a reason (PERCEPTIVE: 4 pieces "Standard_ConstructionError"; IBM: 2 weight-low). The 5 W24x55 exact -> tagged rows come from `--nc1` and are unrelated. |
| 8 | Fleet class transitions, all 1,101 merged-code SDS2 models that have a previous class | (2,2) 1002, (0,0) 87, (0,2) 6, (1,1) 2, **(2,1) 2**, (2,0) 2. The two (2,0) rows (Mooresville "For Field bolt", CONTINENTAL ELEVATOR) are best-of choices between v5.5.7 and v5.5.6.1, which both contain this patch, so they are not caused by it. |
| 9 | Class-1 controls | Code argument: base v5.5.3 always tags GR / GT pieces, so a class-1 model has no grating parts for the hook to touch. The rod paths only replace straight-rod guesses, which are tagged, or rods that turned_local could not read. Fleet: GHJK and hjg went v5.1 class 1 -> v5.5.6.1 class 1, identical solids. These two controls contain no rods or gratings, so they are weak. |
| 10 | Does the fix generalise across the corpus? | live `class_2_partial` (09:47Z): the `mesh_cylinder` stand-in remains in 14 of 1,276 merged-code SDS2 models (38 placements), against 447 of 1,439 older v5.x models (197,245 placements). Grating stand-ins left in merged-code models: 384 `grating_solid_panel`, each with a not-built reason (weight 0.60-0.74x, construction error, no faces, no cross-bar depth), plus 272 `grating_crossbars_from_record` (owner policy). |

## Problems found
1. **"0 models move to class 1" is wrong; the patch understates its own benefit.** The fleet lifted 2 models to class 1
   on this patch alone:
   - PROCTOR & GAMBLE_JOB_VOID (87772ff9, 7.619): its only flaw was 116 `mesh_cylinder` RB1/2 -> cap-axis cylinders,
     steel ratio 1.0224 -> 1.0209, 1,038 / 1,038 valid;
   - DUMMY (07798a94): 1 RB1/4 -> own B-rep.
2. **The "current release" base is stale.**
   - v5.5.4-v5.5.7 have shipped since v5.5.3. v5.5.6 already contains the interim version of this patch, and v5.5.7 is
     on the fleet.
   - The only part not shipped is the `SDS2_GRATING_BUDGET_S=0` off-switch (`>=`). Applying the deliverable patch to
     v5.5.7 would duplicate code.
   - The owner also overrode one tagging rule: cut panels built from partition cells are tagged
     `grating_crossbars_from_record`. In the test jobs that is 5 pieces / 2 placements; the fleet has 272 such
     placements in 5 models.
3. **`_on_stored_face` (grating.py) tests only the covering face's first (outer) loop and ignores its holes.**
   - If a bar or nosing tube ends over a hole in a carrier plate, the cap is added anyway. That cap stays on the
     boundary: a face the source does not store.
   - The weight check cannot see it. This closure path builds 85 pieces / 2,065 placements in the test jobs.
   - I could not measure how often it fires without the box. Fix: reject the closure when the loop lies inside any
     inner loop.
4. **`_name_dia` misparses sizes followed by `x`:** `RB3/4x12` -> 3.0, `HS3/4x4` -> 3.0, `WS5/8x6` -> 5.0,
   `AB 1 1/4x36` -> 1.0 (the regex `\b` fails before `x`). The result is a rejection, so such rods keep the tagged
   guess; nothing wrong is written. The test and fleet names (`RB1/2`, `TWS5/8`, `THD STUD 3/8`) are not affected.
5. **One branch does not give its reason.** When the grating build fails but the panel B-rep closes, the base
   `brep_placed` branch keeps its old note "bar grating written as SDS2's solid panel" without "bars not built: <why>".
   The fleet has 22 such placements in 21 models. The README says every failure names its reason.
6. **Cost and repair-pass dependence:**
   - One Light Tower 1,043 -> 5,640 s and 175 -> 406 MB.
   - SUSQUEHANNOCK 8,898 -> 11,237 s, which is 78 % of the 14,400 s fleet timeout. SLC4 +27 %.
   - The grating budget caps build time only; read-back time is not capped.
   - On SUSQUEHANNOCK, 175 of 1,365 placements of the vertex-merged RB1/4 B-rep (piece 13511, accepted at 1.57x
     SDS2's weight, just under the 1.6 limit) read back invalid until repair pass 1.
   - Under v5.5.7's `SDS2_VERIFY_BUDGET_S`, a repair pass that does not fit makes the final pass leave invalid parts
     out. Such rods could then become skipped parts.
   - Neither SUSQUEHANNOCK nor RIPPLING WOODS (350 merged-vertex rods, never fully converted by the author) has a
     merged-code fleet run yet. **This should be checked once box access is back.**
7. **Unverifiable from here:** the interim / final S3 uploads (annotationprod is not readable with bim), and the
   BOX-C clean-up.

## Not found
* Fabricated bar positions.
* Closed open meshes, other than the contact caps in (3).
* Lost placements.
* New final invalid solids.
* Class regressions caused by the patch.
* Tags removed without weight or geometry proof.

## Reproduce (Mac, read-only, small files)
`review/cmp.py` and `review/pcmp.py` read the author's box outputs (`conv/{v553,v553h}`); `review/hcmp.py` reads the
fleet pairs in `review/pick.json`, downloaded from `conversions/sds2-step/<id>/{v5.5.5,v5.5.6.1}/`.
