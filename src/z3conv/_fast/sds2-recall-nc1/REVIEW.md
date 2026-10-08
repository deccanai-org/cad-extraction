# Adversarial review: sds2-recall-nc1

Reviewer verdict: **confirmed with caveats**. The tools and the numbers reproduce exactly. Finding 1 (the v5.x
regression) is real. It is in fact a code bug, and it is still present in the deployed v5.4.1. Finding 2 ("main-member
holes not cut") does not hold for the evidence the stream cites: those cases are model snapshots taken before
connections were added. The finding and its root cause need to be withdrawn or reworded. Details follow.

All compute ran on BOX-C (i-0d97427e58ca5ef28) in `/work/agentwork/sds2-recall-nc1-review`. Large downloads and
converter builds were deleted afterwards (9.7 MB left). The Mac only staged scripts and read results.
- Review scripts: `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1-review/`
- Outputs and logs: `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-recall-nc1-review/{out,logs,conv}/`

Converter builds were sha256-checked on the box:
- v4c `c5b65d27…`
- v5.3 `81ca1f95…`
- v5.4.1 `0eccc2fb…`

Review conversions went only to the review prefix, never to the fleet `conversions/`.

## 1. What holds (re-run on the box)

| check | result |
|---|---|
| NC1 rerun from scratch, Dupont v5.1 (fresh STEP download and index; NC1 files by sha) | identical: 12,740 / 15,393 holes matched, recall 0.8276; geometric holes 22,352 = stream (manifest 22,345) |
| NC1 rerun from scratch, SAU-WRC d5b3c35e v4c | identical: 2,601 / 2,974, recall 0.8746 |
| Hole detector vs an independent count on the real B-rep (pythonocc XCAF; cylinder faces grouped by axis, radius and arc span) | 35/35 sampled parts agree exactly on Dupont (446 holes); 35/35 on SAU-WRC (165 holes) |
| IFC recall rerun, EQUADOR v5.3 | identical: 0.9869, 2,047 pairs |
| IFC recall rerun, Edge_West v5.3 | identical: 0.8015, 1,479 pairs |
| IFC matcher sensitivity: drop the "thin STEP piece compared on length only" rule / tighten centre tolerance from 25 to 10 mm | Edge_West v4c 0.944 / 0.944 / 0.9265; EQUADOR 0.9869 / 0.9869 / 0.9701; Cats Rail 0.9607 / 0.9607 / 0.9507. The recall numbers are not inflated by the loose rules. |
| v4c vs v5.3 on 17 jobs (from the report) | 31,574 → 31,694 holes matched; 4 better, 13 equal, 0 worse |
| Detector vs v5 manifest hole count | within 1 % on 36 of 51 v5.x runs |

## 2. Finding 1, the v5.x "absurd extent" regression: confirmed, but the root cause and proposed fix are wrong

The stream's root cause is that the rule "tests piece-table / vertex records". The fix it proposes is to test the B-rep
bounding box instead, or to exempt bar sections. Both are wrong.

**Actual cause: a type bug.**
- In v5.x, `convert()` runs with `shared=True`, so `brep_placed()` returns the tuple `("shared", solid, trsf)`.
- In the special-piece branch, `to_step2.py` (v5.3 line 1078, v5.4.1 line 1263) calls `_absurd(sh)` on that tuple.
- `BRepBndLib.Add_s(tuple, …)` raises `TypeError`, and `_absurd` catches every exception and returns True.
- So every exact-B-rep piece that reaches that branch is dropped. No extent is ever measured.

Proof:
- An instrumented v5.3 copy logged the exception for all 1,504 Edge_West SB1/2 drops: `bnd_exc: TypeError("Add_s(): incompatible function arguments…")`, builder `exact_brep`.
- The same logging gives the same result on 2 other jobs from the stream's list. In each, v4c writes the same pieces as `exact_brep` and v5.3 drops them:

| job | SDS2 | pieces dropped by v5.3 |
|---|---|---|
| 888 Boylston (b9c720b9) | 7.323 | 94: #8 COUPLERS 58, #6 BENT REBAR 18, #6 COUPLERS 18 |
| PSU_BNR (4e990883) | 8.004 | 27 SB1/2 |

So the bug is not specific to bar sections. "Exempt round/square bar and rebar" would still drop the couplers.

**One-line fix tested:** `_absurd(sh[1] if isinstance(sh, tuple) else sh)` (review copy `v5.3fix`, Edge_West):

| | skipped | class | pieces written | read-back | IFC recall |
|---|---|---|---|---|---|
| before (v5.3) | 1,504 | 0 / broken | 3,026 | | 0.8015 |
| after (v5.3fix) | 0 | **2 (B)** | 4,472 | 8,052 / 8,052 valid | 0.9275 |

**Still present in deployed v5.4.1:** Edge_West v5.4.1 skips the same 1,504 SB1/2 pieces and stays class 0.

**Geometry check, independent of the stream's tools:**
- The job's IFC has **264** SB1/2 IfcMembers (the stream says 245; 245 is the number that v5.3 leaves unmatched).
- Their PCA extents are 908 / 905 / 891 × 13 × 13 mm.
- All 264 coincide with v4c SB1/2 solids (XCAF, oriented-box extents identical) to within 1e-8 mm.

**Minor:** the IFC drop from v4c to v5.3 is 277 pairs. Of these, 245 are SB1/2. The other 32 are WAGNER 1980ST
handrail brackets: v4c builds them with `plate_fallback`, v5.3 with `bent_plate_fallback`, and v5.3's shape no longer
matches the IFC. So the fix lifts Edge_West to about 0.93, not the 0.94 claimed.

## 3. Finding 2 ("main-member holes not cut", Novelis as the clearest evidence): refuted as a converter defect

**Novelis is itself an ABM snapshot.**
- Job path: `MT14_042 (Novelis BP 18)/08. Uploads/ABM/09-26-14/Novelis_Job/`.
- Its NC1 files come from fabrication releases T11 / T15 / T16 / T20, dated 12-06-14 to 12-19-14, about 3 months later.
- The NC1 header order line is `Novelis_Job`.

**The 55 parts / 2,698 holes are many-to-one.**
- The 55 distinct NC1 marks collapse onto only **12** STEP pieces.
- For example, 14 different fabrication column marks (2001C1, 2002C1, …) all match `COLUMN #85 / W14x120 (piece 3)`, which is placed 20 times.
- In the fabrication model those columns differ by hole pattern. In the ABM snapshot they are one identical, undetailed piece.

**Real B-rep check (XCAF), v5.3 and v5.4.1, top 8 parts:**
- 0 cylindrical faces on any of them.
- **0 BOLT instances** within 30 mm of any of them. The model has 1,460 bolts elsewhere.
- Only the framing beams touch the columns.

**The deployed v5.4.1 (bolt-derived holes) derives 0 holes on Novelis** (bolts_checked 1,460) and cuts 0 of the 2,698.

**Same picture on the other jobs cited** (real B-rep, top 8 strict-zero parts; v5.4.1 run by the reviewer):

| job | model date vs NC1 dates | top-8 parts with any bolt within 30 mm | v5.4.1 holes on the strict-zero parts |
|---|---|---|---|
| THE RESIDENCE AT STAMFORD (7.425) | model 02-23-17; NC1 03-20 to 04-25-17 | 0 / 8 | not run |
| TANGER (7.312) | backup 19-MAY-15; NC1 08-13 to 09-15-15 | 2 / 8 (10556B2: 30 bolts; 7018C1: 4) | 0 of 436 (bolts_checked 1,277) |
| BMW BAY checkered plates | | 0 / 8 (8 × 25.4 mm NC1 holes, no bolts at all) | 0 of 397 (v5.4.1 derived 73 holes elsewhere) |

So the action "hand these lists to v5.4; recall should rise from 0 toward 1" fails when tested: 0 of 2,698 / 436 / 397.
Only TANGER 10556B2 and 7018C1 remain as possible real gaps.

**The version dependence claim is confounded.** The claim is "v4c main-member recall 0.866 on 7.1xx vs 0.361 on
7.3xx, because 7.2/7.3 hole blocks are not decoded". In fact:
- 7.3xx contains Hartford ABM (21,890 NC1 holes, recall 0.001) and Novelis ABM.
- Excluding jobs with ABM in the path, or with the early-state flag, 7.3xx main-member recall is **0.612**.
- Many 7.3xx jobs score 0.91–0.99: BMW BAY 0.986, BRIDGEPARK 0.983, ISU FINE ARTS 0.976, SEASIDE 0.910.
- The 0-recall 7.3xx jobs are CONTRA (B4ABM snapshots), VALLEY GROVE (model 06-19-18; NC1 10/11-18) and NORDISK (backup before its NC1).
- The "undecoded 7.2/7.3 member-file hole blocks" root cause is not shown by any evidence in the deliverable.

## 4. Headline tables mix in snapshot artefacts

The NC1 headline "v4c 0.536" includes the ABM and early-state jobs. The stream says these should be excluded, but
aggregate.py only flags them. Recomputed from `report_interim4.json`:

| label | all jobs | excl. early-state flag | excl. flag or ABM path |
|---|---|---|---|
| v4c | 0.536 (59 jobs) | 0.649 (56) | 0.784 (47) |
| v5.3 | 0.813 (26) | 0.815 (25) | 0.852 (22) |

Also, "parts" in the tables count NC1 files, including several releases of the same mark. SAU-WRC, for example, has
1,526 files for 1,022 marks. They are not distinct pieces.

## 5. Other notes

- **Matching is only longitudinal on rolled members.** NC1 → STEP hole matching compares x along the member and the diameter only; y and face are ignored. "Matched in position" overstates this. In the B-rep spot checks it caused no visible error.
- **No harmful side effects.** The stream fabricates no geometry, does not loosen the grader, and writes nothing to the fleet `conversions/`.
- **Inventory counts are internally consistent:** d12b 241,149 verified + 2,633 sha mismatch + 15,872 no candidate = 259,654.

## Required corrections before integration

1. Replace the root cause and fix in finding 1 with the tuple bug and the one-line unwrap (or make `_absurd` reject only on a measured extent, never on an exception). Apply it to v5.4.1. Re-run the 13 jobs.
2. Withdraw Novelis, STAMFORD and the BMW checkered plates as converter defects. Classify them as snapshot state, like the other ABM jobs. Drop the 7.2/7.3 hole-block root cause. Keep only cases where bolts cross the member (TANGER 10556B2 / 7018C1) as candidates.
3. Report the NC1 totals with ABM and early-state jobs excluded. Mark "parts" as NC1 files.
