# Adversarial review: hole-tolerance-residue (DB1 old-engine hole tolerance + not-a-ply skip)

Reviewer run: 2026-10-02 ~03:00-03:50Z. All heavy work ran on BOX-B (i-076e73980707c7dbe) in /work/agentwork/htr-adv-review, which has since been removed. On the Mac I only staged small files, ran aws s3 cp/ls and did quick JSON tallies.
Results: s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/htr-adv-review/{census/kit_ig,kit_ip,kit_nx, full/, nc_ik.json, ifc_holes.json, job.log}
Tools and analysis: s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/htr-adv-review/ (instrument.py, relharness.py, myrun.py, nc_ik_check.py, ifc_holes.py, analyze_mine.py, rv_adv.json)

## Verdict: CONFIRMED WITH CAVEATS

The patch is correct. The headline numbers reproduce exactly on an independent kit base. An independent ground truth (Tekla's own bolted-part relation records) shows that the new "not a ply" skip removes no genuine hole in 99.95 % of cases. I found no fabricated geometry, no grader loosening and no STEP regressions. The caveats concern rollout and a few small misstatements, not the patch logic.

## What I checked

1. **The patch applies and the md5s match.** `patch -p0` on the code-i/j base (db1bolts 0f67b818..., db1step 6039ca91...) gives 079ffea6d105142ff41e8d2a9340c8aa / 72029bbf4e7f3b1c0048379843a2e249. The guard-only baseline differs from the base only by the 2-line catalog guard.

2. **Census reproduced on a different base.** I used kit_i (code i) + guard as baseline and kit_i + patch as patched, versus the author's code-j kits.
   - All 97 old-engine DB1s ran with 0 errors.
   - Per model, 11 bolt_stats keys plus the full hole-diameter histogram are identical to the author's kit_jg / kit_jp5 in 97/97 (baseline) and 97/97 (patched).
   - All old-engine models: nominal 23,897 -> 0; models with nominal > 0 76 -> 0; holes 645,819 -> 627,878; 2,051 no-hole; 15,890 not-a-ply; hole accounting mismatches 0.
   - Tagged 54: nominal 12,334 -> 0; models 54 -> 0; holes 278,881 -> 271,549; no-hole 48; not-a-ply 7,284.
   - Deployed code n run with the relation filter off (DB1_HOLE_REL=0) also gives nominal 0 in all 97 models.

3. **Ground truth for the not-a-ply rule, using a source the author did not use.** Code n decodes Tekla's type-10 relation records (bolt group -> bolted parts). I instrumented a copy of code n, turned the relation filter off, and logged every geometric (part, bolt) hit against that list. All 97 models:
   - Geometric plies: 554,120 in Tekla's list, 78,656 not (87.6 % agree). This confirms the list is meaningful.
   - Pairs the patch skips as not-a-ply: **16,000 of 16,008 are not Tekla-bolted parts**, so they are correctly skipped. 0 have no list.
   - **8 are Tekla-bolted parts that lose their hole:**
     - PL310*50 x3 in 0762effe61de
     - PL360*50 x2 in 0bbac8fc66cc
     - PLT160*10 x2 in 772329a2d97d
     - PL180*10 x1 in 6f0dcc7daa09

     In all 8 the bolt is perpendicular to the member axis, its whole ±window lies inside the plate, and the rule was inside_window.
   - The author's open issue named PLATE200*50 and PL155*50. Tekla does not bolt those (they are correctly skipped). The issue missed the two 10 mm plates.
   - Rods, concrete blocks and the W shapes (W12X30, W27X102, W14X48, ...) are all "not bolted" per Tekla, so skipping them is right.

4. **Production path on 3 models the author did not test** (convert_one on ifcopenshell 0.8.4 -> ifc2step6 hybrid -> step_check):
   - **f639717b04db:** 3,996/3,996 valid in both runs. Approx products 268 = 268. Nominal 247 -> 0. Holes 26 -> 24 mm x137, 33 -> 30 mm x72, 11 -> 6 mm x38. Hole count 1,112 unchanged.
   - **6eabb07e7145:** 9,022/9,022 valid in both runs. Approx 0 = 0. Nominal 30 -> 0. 18 -> 16 mm x22, plus 8 W14X48 non-plies skipped; Tekla's list does not include those 8.
   - **0dd3da934923:** 41,517 -> 41,489 solids, all valid. Approx 280 = 280. Products 11,844 in both. Nominal 294 -> 0.
     - The 28 fewer solids come from 14 ROD15.875 that baseline split into 3 solids each by boring along the axis; patched writes them as 1 intact solid each.
     - 26 ROD19.05 got their bored-away ends back: bbox 381 -> 476 mm, volume +25 %.
     - 108 plates lose volume (larger anchor holes: 38.1 / 39.68 mm). 23 W shapes gain volume (holes no longer cut in non-plies).
     - So no product is lost and no solid is invalid.
   - The author's 5 production JSONs agree with the claims, and approx_products is unchanged in every pair. Across all 8 pairs, the patch never makes the best-of key worse.

5. **Hole-size rule (d + t) against Tekla NC.** I wrote my own independent DSTV parser (crude; it undercounts BO lines).
   - Deployed residue sizes never appear (33 / 11 / 30.162 / 14.287).
   - Patched sizes do appear: 30 mm and 20 mm (t = 0), 41 mm (MM30 + 11) and 45 mm (MM20 + 25) (t > 10) in a7f94f2edc0f; 10 mm (5a2284473e4e); 7.94 mm x8 and 28.57 mm x36 (6b87b724b554).
   - This agrees with the author's and the earlier reviewer's counts (30 mm 116 vs 116 cut).

6. **Crash guard.** Code i/j raise KeyError 's' in catalog_geometry on 3585d86a380d, 48e010c8ec25 and 7c68f0c9874e (seen in the code-i census .err files). With the guard there are 0 errors.

7. **Grader.** build_index.py derives hole_clearance_nominal from holes_nominal_clearance (unchanged meaning). It now also maps holes_in_slotted_groups_cut_round to a new 'hole_slotted_cut_round' stand-in, which makes grading stricter, not looser. Of the 23,897 nominal holes, 17,672 clear by decoding and 6,225 because they are no longer cut (not-a-ply); point 3 validates the latter.

## Caveats and problems found

- **Rollout is not finished, and best-of blocks part of it.** The patch is already in deployed code m/n. The current index still has **44 DB1 models tagged hole_clearance_nominal**, every one an old-engine model where the patched code gives 0.
  - 10 models (0bbac8fc66cc, 14e4060080fa, 27a9febf9f71, 4671ea562003, 48e010c8ec25, 575da79b6096, 9f619582d242, bceea537cbda, cd9207295eb9, fade48f92ad8): the code-n run was rejected by best-of, and an older l/h STEP with nominal holes is served. Example: 4671ea562003, approx products l 17 vs n 102. This comes from other code-n changes, not this patch (see point 4).
  - The rest have not been re-run on m/n yet (l x18, i x7, j x3, h x2, f x1, 3 reused).
  - So "Expected after re-run: 0 tagged" holds only once best-of accepts the new STEP, or the approx regression in n is fixed.
- **In deployed code n, the not-a-ply rule now only removes the 8 genuine holes.** The type-10 relation filter runs first and already drops all 16,000 non-bolted pairs; none of the hits lacks a list. Suggestion: in code n, skip the inside check when the part is in the group's type-10 list, or keep it only for groups without a list. These 8 bolts run in the plate's plane, which may instead mean the plate is oriented wrongly; worth a look.
- **Some numbers do not match.**
  - "63,974 bolt strings" does not match any count I can reproduce: 108,178 bolt-group records in 97 models (all 11 fields, max 58 chars), and 44,851 in the tagged 54. The claim itself holds.
  - The 50 mm flat-bar list in the open issue is wrong, as described in point 3.
- **The NC proof for t > 10 is partial.**
  - MM30 + 30 -> 60 mm (220 holes in 291547d3c10f, 217 in 3c6b9781f5d0) has no NC match anywhere.
  - The 70 mm IK circles were found only by the author's parser; neither the earlier reviewer's parser nor mine found IK circles.
  - The t > 10 rule rests on the 41 / 45 mm BO matches and Tekla's documented hole = bolt size + tolerance.
- **The slot follow-up lead may be wrong for some groups.** 6eabb07e7145 NC has 31.75 mm round holes x1,056, which equals 25.4 + 1.59 + 4.76 (slot x field) for the A490SC groups. That looks like Tekla "oversized" holes (hole = d + tol + x), not slots, so check this before cutting slots. This does not affect this patch.
- **Tekla IFC exports in the 6eabb07e7145 folder contain no openings or fasteners** (ifc.ifc from Tekla: 0 openings), so they could not be used as ground truth.

## Regression risk

Low. Hole positions, bolts, washers and axial fit are unchanged in 97/97 models. STEP validity and approx_products are unchanged in 8/8 production pairs. The only geometry removed is in parts Tekla does not bolt, apart from 8 holes, and severed rods become whole again.
