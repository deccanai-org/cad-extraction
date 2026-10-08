# Adversarial review: stream cut-not-applied (P1-P15)

Reviewer job slug: `cut-not-applied-review`. All heavy work ran on BOX-B (i-076e73980707c7dbe), in `/work/agentwork/cut-not-applied-review`.
The Mac only edited small files and copied small files to and from S3.

- Results: `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied-review/res/`
- Review scripts: `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/cut-not-applied-review/`
  (rv_truth.py, dump_old.py, adv_sum.py, rep_p4.py, lenrep.py, lenrep2.py, p5_check.py, pcmp.py, csum.py, worse.py, mkkits.py, apply_cut_patch_o.py)

How the kits were built:
- **Code n kit:** every kit file at its latest S3 version up to 2026-10-02T04:40Z (worker CODE z3-db1-2026-10-01n).
- **Code o kit:** the current S3 versions (CODE z3-db1-2026-10-01o, deployed 04:48:55Z, after the deliverable was written).
- **Patch:** the deliverable exactly as uploaded to `s3://annotationprod/.../db1/fixes/cut-not-applied/`.

All sources were sha256-verified: the 106 data-3 DB1 files against the index (ids are their sha256), and 16 Tekla DB1+IFC truth pairs against pairs.json.

## Verdict: confirmed with caveats

The core evidence reproduces exactly, and it holds up on truth cases the stream never used. There is no data loss, no fabricated phantom geometry and no grader loosening. Problems:

1. **The patch does not apply to the kit that is deployed now (code o).**
   - Result: `P6 old-engine body: ANCHOR MISSING (0)`, then `RESULT FAILED (nothing written)`. Integration steps 1-2 ("copy into the code-n kit", check against the code-n checksums) are therefore stale.
   - Cause: code o (tekla-slots) inserted a `RECT_THIN_Z` block right after `kind, v, how = section_for(...)` in the old-engine `body()`.
   - Fix: one alternative anchor. The reviewer's rebased script is `agentjobs/cut-not-applied-review/apply_cut_patch_o.py`; every other P1-P15 anchor applies unchanged.
   - Check: code o + rebased patch gives the same corpus totals as code n + patch (604,100 written, 101,921 applied, 6 unbuilt, 951,500 holes), with no per-model flags.
   - Side effect: code o's own thin-plate swap and P15/P8 are the same rule on old engines (code o alone: holes 927,914 -> 935,275). With the patch, code o's `rect_plates_thin_side_to_z` statistic will read 0.
2. **P12 (the fork's new-engine fittings, plugged in unchanged) is not regression-free on other new-engine models.** The deliverable says "No part got worse"; that holds only on the fork's own validation set. Per-part volume vs Tekla's own IFC geometry, on pairs the stream did not use:
   - 7.64 n764a: 238 better / 0 worse.
   - 7.82 n782: 181 / 0.
   - 8.62 n862: 954 / 1.
   - 8.07 n807: 155 / 78.
   - 8.53 n853: 216 / 77 (bbox worse 60).
   - 8.74 n874: 31 / 22.
   - 8.95 n895: 23 / **328**.

   Total volume error still falls on every pair. data-3 has three 8.53 models. The fitted parts carry no approx tag, so wrong trims would be graded as exact. See the breakdown section below.
3. **Large unverified removals on 8.53.**
   - In 1d8972fb, a W14X730 loses 88% of its volume (2 new cuts), 13 PL114.3X1016 lose 43%, and W14X176 / W27X539 lose 36-38% to P12 trims. All STEP solids stay valid. There is no truth for this model.
   - Correction to the reviewer's own statistic: the decode-level "lengthened up to 8.4 m" cases ('5080*168.275' concrete panels, 27a9febf / cd920729) are oblique fittings. Their fitL includes the R·tanθ margin with R ≈ 5,083 mm, which the half-space clips again. In the 27a9febf pipeline no part gains more than 10% volume. These are not real lengthenings.
   - Unrelated to this patch, already in code n: K-joists (22K5, 12K1, 16K2, 'catalog') are written with an IFC extent of 83-106 m along an axis of 5.8-9.9 m, and STEP volumes about 9x a K-joist's. This is for the profile / joist owner.
4. **One explanation is wrong, though its conclusion holds.** For the IRON_ORE HSS6X6X1/4 parts, Tekla's NetVolume does *not* ignore the fitting. NetVolume = 3,709.7 mm2 (5.75 in2, sharp-corner area) x Tekla Length 9,934.96 mm = 36,855,408 exactly. The final kit's length now equals Tekla's (bbox error 149 mm -> 0.0). The remaining 2.9% is the section area (ours 3,602.7 mm2), not the fitting.

## 1. Patch integrity
- The uploaded patch applied to code n produces files byte-identical to `kit_patched`: db1old ef069976, db1dec 67365890, db1step aaf2c269, fittings cfc6cd23. A re-run reports 'already applied' for every edit.
- fittings.py is identical to db1_v2/eng/fittings.py (md5 cfc6cd23).

## 2. Corpus, all 106 models, convert only (independent re-run on BOX-B): every total reproduces exactly

| Metric | Code n | Code n + patch |
|---|---|---|
| Written solids | 667,571 | 604,100 |
| Decoded parts | 751,839 | 755,110 |
| Cut parts | 39,937 | 106,610 |
| Cuts applied | 38,092 | 101,921 |
| Unbuilt cut bodies | 260 | 6 |
| Models with unbuilt cuts | 9 | 2 |
| Bolt holes | 927,914 | 951,500 |

- Status changes: 0. Non-zero return codes: 0.
- No model has fewer holes, fewer decoded parts or fewer applied cuts, and no axis-guard count changes.
- Flagged models: 0762 unbuilt 1 -> 0; 1d8972fb 124 -> 0; a9444257 68 -> 0. dcdf359e keeps 5 and 2ffffe4d keeps 1, as the deliverable says.
- The written-solid drop never exceeds a model's count of operative cutters by more than 5.

Decode-level dumps of all 101 old-engine models, code n vs patched:
- Non-cut parts lost: 0. Profile or axis changes on the same pid: 0. Every removed part is obj_type 11 and named as a cutter by a type-11 relation.
- Geometric duplicates (same profile and O/E within 1 mm): 8,842 -> 3,231.
- P3 cannot duplicate a pid: the salvage loop dedups by pid and run records win.

## 3. Truth: per-part comparison with Tekla's own IFC geometry

Method: mesh volume and bbox in our part frame (ifcopenshell, openings applied), joined by GUID.

| Pair | Bbox <= 1 mm | Volume <= 1% | Sum of volume errors | Per part (vol) | Phantoms | Tekla parts lost |
|---|---|---|---|---|---|---|
| IRON_ORE 7.24 | 2,273 -> 2,990 / 3,006 | 461 -> 590 | 0.925 -> 0.560 m3 | 1,190 better / 13 worse | 3,267 -> 2,093 | 0 |
| FIELD_BOLT_IRON 7.24 (new to this review) | 2,281 -> 3,009 / 3,025 | | 0.988 -> 0.559 m3 | 1,203 / 13 | | 0 |
| GSK 7.24 | 809 -> 817 / 817 | 786 -> 794 | | 8 / 0 | | 0 |

- IRON_ORE: the phantom drop is exactly the 1,174 P4 cutters; none is in Tekla's IFC.
- FIELD_BOLT_IRON is a different DB1 and a different IFC export from IRON_ORE, so it is a semi-independent case.
- IRON_ORE worse parts:
  - PL177.8*19.05 / *9.525: bbox goes from 79-84 mm off (rotated) to exact; Tekla's geometry has no bolt holes.
  - HSS6X6X1/4: bbox 149 mm -> 0; the gap is the section area.
  - PIPE1-1/2SCH40: bbox 82 mm -> 0; Tekla has an extra cut we do not decode.
- GAMBRO 7.24: this is the part-by-part check the stream abandoned after a kernel crash; it completed here (19,924 joined parts).
  - Bbox within 1 mm: 14,731 -> 17,601. Volume within 1%: 4,293 -> 6,960. Sum of volume errors: 21.09 -> 0.795 m3.
  - Per part, volume: 2,759 better, 50 worse. Bbox: 2,884 better, 2 worse.
  - Phantoms 20,929 -> 10,605: the P4 cutters, none of which is in Tekla's IFC. Tekla parts lost: 0.
  - The worse parts are W14X22, W24X76 and W16X77 whose bbox becomes exact but whose volume drops about 5% below Tekla's. This is possibly a P4 cope that Tekla's exported geometry does not have; unexplained.
- Unusable pairs (0 GUID hits): LARD_ABM 7.24 (its IFC is from LARD_PLANT), and n764b, n798, n837.

## 4. Truth: Tekla's own part-list reports (41 old-engine data-3 models, 136 report files)

**P4, profile-quantity test** (one list per model; the 8 largest cutter profiles per list):
- In 66 profile groups covering 5,500 cutters, Tekla's quantity is closer to our kept count than to kept + cutters. Examples: 6f0dcc7d D20, Tekla 69 = kept 69, 249 cutters; 0632e878 D20, 56 = 56, and L150*90*10, 18 = 18.
- 4,163 cutters have profiles that are neither in the list nor among kept parts (PLT9, PLT16*85, ...).
- 1 contrary group: 748b957c / 305be94d PD40*3. Those are 36 identical 1,720.9 mm cutters, each coping a different PL65*65 or L65*65*6, against a single Tekla row (HR21 PD40*3 1721, qty 1). Code n wrote them as 36 overlapping phantom rails.

**P13 perpendicular fittings** (fitted length exact): Tekla's listed length matches the fitted length 255 times, the original 4 times, both 6 times.

**P13 by solid extent along the member axis** (written IFC, both kits): only the final kit matches 119 times, only code n matches 55 times.
- Perpendicular, lengthened: 30 vs 0.
- Oblique: 45 vs 12.
- Line cuts: 39 vs 37, i.e. neutral. This agrees with the deliverable's own L50*50*6 open issue.
- Note: comparing the axis length (fitted L) is biased for oblique fittings, because the R·tanθ + 1 mm margin is clipped later. Do not use it.

**P3:** salvaged parts match the lists (profile and length within 1 mm) 41.4% of the time, against 21.9% for all kept parts.

**0762 cuts that remove a lot:**
- 10 x PL10*70 L150: 104,995 -> 67,497 mm3 = 0.530 kg; Tekla net 0.5 kg, gross 0.8 kg.
- 4 x PL10*200 L538: 1,501,597 -> 981,510 mm3 = 7.70 kg; Tekla net 7.8 kg, gross 11.8 kg.

## 5. Full pipelines (decode, IFC, ifc2step6, OCC read-back)

| Model | Solids valid (code n -> final) | Notes |
|---|---|---|
| 0762 | 2,341/2,341 -> 2,239/2,239 | Written 834 -> 782, applied 90 -> 239; equals the deliverable |
| c8d753af | 7,696/7,696 -> 3,835/3,835 | 3,861 cutters removed: PL86.2 / PL152.4 slabs cutting 26K10 / KSP joists, all obj_type 11 |
| ea1a25eb | 7,905 -> 5,503, all valid | |
| 27a9febf | 25,806 -> 22,921, all valid | |
| 1d8972fb | 11,302 -> 11,302, all valid | |
| a9444257 | 35,977 -> 35,977, all valid | Approx products 156 -> 173 (+17 tagged); tag names <= 84 characters, under the 120-character STEP cut |

## 6. P5 (isolated relation records, new engines)
- 1d8972fb: 18 links, each cutter within 359 mm of its parent's axis.
- 7a6a190d: 29 links, within 152 mm, the same distribution as normally linked cuts.
- Conclusion: plausible.

## 7. P12 regressions on new engines (breakdown)

Method: worse.py, per part, Tekla's IFC geometry vs code n vs final. "More cuts" means the final kit added half-spaces; "same cuts" means a perpendicular trim, which adds no cut.

**n853 (8.53, McDonald's Deventer; data-3 has three 8.53 models): 77 worse.**
- 66 are perpendicular P12 trims that shorten parts Tekla's own geometry leaves untrimmed:
  - KK70/5 (13 parts), KK100/60/4 (12), L70/7 (8), KK60/5 (7), HEA140.
  - Example: KK60/5 goes 78,458 -> 65,021 mm3 (−17%); Tekla has 78,454, equal to code n.
- 11 have more cuts. One KK60/4 with a single new half-space shows 181,072 -> 809,872 mm3 (4.5x) in the reviewer's triangulated-mesh volume. That is a measurement artifact: the OCC B-rep of the same element (ifcopenshell 0.9 + OCC GProp) is 180,431 mm3, one valid solid (Tekla 181,069; code n 181,339). It is not filled geometry. The full n853 STEP run was stopped (too slow), and the direct OCC check replaced it.

**n807 (8.07, Frito-Lay): 78 worse, 155 better.**
- 61 worse are perpendicular trims. Examples: HSS8X8X1/4 31.4e6 -> 25.5e6 mm3 (Tekla 32.1e6); C8X11.5 −3.1%; W21X50 −3%.

**n895 (8.95): 328 worse, all with added half-spaces.**
- 288 are '15*233' parametric panels that code n already writes 32% below Tekla's volume (a profile problem, approx-tagged); the half-spaces take them to 42% below.
- The rest are PL480*12, PL480*8 and PL440*12 plates (P15 and P12 together).

Caveat: the DB1 and IFC of a pair may come from different saves. pairs.json maps one IFC to several DB1 backups. A fitting added after the export would show up as "worse". These regressions are therefore unproven errors, not proven ones. Still, the deliverable's statement that P12 makes no part worse does not hold beyond the fork's validation set.

## 8. What was not verified or not closed
- Line cuts on old engines: the 624 'end normal flipped' heuristic cases, and L50*50*6 over-removal (the deliverable's own open issue). Against Tekla's lists, line cuts are neutral (39 matches only after the patch, 37 only before).
- 1d8972fb: the large 8.53 removals (W14X730 −88% and others) have no truth.
- GAMBRO: the 50 worse W shapes (bbox exact, volume −5%) were not individually analysed.

## 9. Required before integration
1. Use the rebased patch for code o (one extra alternative anchor for 'P6 old-engine body'), or have the builder rebase. Re-check against the code-o checksums, not the code-n ones in BASE_MD5.txt.
2. Either gate P12 trims on new engines behind an approx tag, or investigate the n853 / n807 trim regressions before counting fitted new-engine parts as class 1.
3. Fix the deliverable text: the HSS6X6X1/4 explanation (section area, not NetVolume ignoring the fitting), and "no part got worse" for P12, which only covers the fork's set.

Box cleanup: all reviewer processes were stopped, and /work/agentwork/cut-not-applied-review went from 5.9 GB to 1 MB. Results are kept in S3 under res/ and res_final/.
