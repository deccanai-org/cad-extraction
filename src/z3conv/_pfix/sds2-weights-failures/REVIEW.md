# Adversarial review: sds2-weights-failures

**Verdict: REFUTED as "ready".** Most of the patch is sound and worth shipping, but not as delivered.

What holds up:
- The converter patch's own before/after numbers reproduce exactly on BOX-C.
- The stud, rod and anchor weight fixes carry over to 12 family-weight models the author never ran.
- 13 live class-1 jobs come out identical.
- No geometry was invented and no tag was removed without proof.

What has to change before it ships:
1. **It cannot go onto the fleet as it stands.** The fleet switched to **v5.5.5** at 05:11Z. The v5.5.3 patch fails 7 hunks on
   v5.5.4 and v5.5.5. Applying the hunks that do fit leaves `stats.update(stats_nt)` and `_wpart` undefined, so every job
   fails with a NameError. It needs a rebase onto v5.5.5. v5.5.4 already ships the CSU hunk and a `_section_ok` path that
   overlaps `_stock_match`.
2. **Regression, lost real parts: the new `>= 10x and +50 lb` fallback gate.** It compares a fallback solid with SDS2's
   recorded piece weight even where that weight is known to be meaningless:
   - **CSU (a target job):** 72 HSS6x4x3/8 / HSS4x4x3/8 members (piece-table L = 0, weight 0.08 lb; the members are about
     100 lb) are deleted. The fleet's v5.5.5 writes all 14,506 pieces.
   - **SDS_MISC_TRAINING_JOB (0fb2c32a):** 17 of 67 GR/GT bar-grating pieces are deleted. SDS2 weighs grating as the open
     mesh, and `track()` excludes G[TR] for exactly that reason.

   This contradicts the README's "no pieces were lost".
3. **Gaps in the no-piece-table path:**
   - The read-back count breaks when a job holds only unindexed parts (proven: 2,833 parts read back as "1 solid, 1 valid").
   - The converter's duplicate check is skipped, so placements are duplicated and nothing reports it.
   - It writes piece files that the indexed path never places.
4. **The proposed grading rule effectively turns off the class-1 weight band for SDS2.** Three of the five class-1 lifts
   depend on it. This is an owner decision, but the effect is larger than the README says.

All runs were on BOX-C (i-0d97427e58ca5ef28), in `/work/agentwork/sds2-weights-failures-review`:
- Command: the fleet's own `sds2_to_step.py JOB -o X_stage2.step --stage 2 --verify`.
- Job folders were fetched with the fleet's layout rules (`rrun.py`).
- Each run was graded with the worker's acceptance rule (`publish2`, using the run's own `run_batch.parse_log`), plus the
  worker's `manifest_summary` and `piece_inventory`, plus the coordinator's `classify_sds2` and `explain` (`gradechk.py`).
- Grading used the *current* control files (worker.py b0de7f95, build_index.py 93ebaa4e, live rules.json), both unpatched
  ("cur") and with the deliverable's worker and coordinator patches ("new").

Trees:
- b553 = pristine v5.5.3 (706e1289…).
- w553 = v5.5.3 + `sds2-weights-failures-v5.5.3.patch`, byte-identical to the author's `work553` / `w553b`.
- b555 = pristine v5.5.5 (2a6e5b68…, the fleet's current zip).
- b54 / w54 = v5.4 (bf4a07fc…) with and without the v5.4 patch.

Results: `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures-review/`
(`<tag>/<job id>/` manifests, pieces.csv, skipped.csv, logs, rc.json; `grade.json`; `nxcmp.json`; `probe_rod.json`).
Scripts: `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures-review/`, with a local copy
in `review/`. The Mac only read small JSON / CSV files.

## 1. The deliverable's own before/after, re-run: CONFIRMED

| job | v5.5.3 (b553) | v5.5.3 + patch (w553) | README |
|---|---|---|---|
| POLICE HQ 7.135 (13e09cfa) | rejected `invalid_solids`, 25,457 / 25,411; 2 C | accepted, 25,411 / 25,411; 46 `exact_solid_invalid_at_placement`; steel 1.003; 2 B | same |
| TATTIER 7.312, no piece table (86b5ce39) | FileNotFoundError; 2 C | accepted, 59,265 / 59,265; 6,592 unindexed, 644 envelopes, 17,343 bolts; 2 B (new rule: `source_file_missing`) | same |
| CSU 7.312 (347cb74f) | ValueError (class 3) | accepted, 14,438 / 14,438; steel 1.030; 2 B, but **72 real HSS members deleted** by the new gate (section 2) | 2 C (the author graded without the piece inventory), "72 pieces gated" |
| 100_Binney 7.243 (a47a1307) | ValueError (v5.5.5 fails too) | 1 / 1; 2 C | same |
| processing-Ted 7.115 (1b5682da, 72f05999) | 2 B, steel 0.793, L family | **1 A** (L8x8x3/4 exact; 4,000 lb record listed as an outlier) | same |
| YSIDRO 7.135 (1b39fd69) | 2 B, 0.840 | 2 B, 0.923 (current rule); **1 A** with the rule | same |
| TEST1 7.331 (799ba840) | 2 C, 1.0585 | 2 C; **1 C** with the rule | same |
| SHOAL CREEK 7.135 (c46e0c62) | 2 B, L family | 2 B; **1 A** with the rule | same |

The author's `parse_log` claim (31 jobs promoted without re-conversion) was checked on 3 of the fleet's own
`_not_accepted` stage-2 logs. In each, the base parser rejects and the patched parser accepts:

| log | base parser (solids / valid) | patched parser (solids / valid) |
|---|---|---|
| PSU Music Hall | 6,181 / 6,166 | 6,181 / 6,181 |
| Misc_1144, the fleet's own **v5.5.3** re-run at 05:05Z | 7,516 / 7,508 | 7,516 / 7,516 |
| "old" | 37,597 / 37,455 | 37,538 / 37,538 |

The "ratio" and "'holes'" patterns occur once per pass, so taking the last match is safe.

The v5.4 patch gives the same results as the v5.5.3 patch on 4 jobs: processing-Ted, YSIDRO, VIOLET STREET and TRAINING
JOB, plus RMC as a control.

## 2. Stage-2 fixes on DIFFERENT models

| job (not run by the author) | v5.5.3 | patched |
|---|---|---|
| CCJ_job copy 7.132 (48b139d1) | rejected `invalid_solids`: 42,005 / 41,744 first block, 256 invalid after both repair passes; 2 C, live STEP = 10,956 member solids | accepted, 41,750 / 41,749. **255 placements dropped** (`exact_solid_invalid_at_placement`, 4.4 % of 5,838 placed) and 1 invalid left; steel 1.019; 2 B |
| 9NOV_330PM 7.132 (ef633da3) | rejected: 41,994 / 41,733; 2 C | accepted, 41,739 / 41,738; 255 dropped, 1 invalid; 2 B |
| AGRANCLISSEMENT copy 7.312 (713dae63) | steel 1.657, manifest class 0, rejected; 2 C (v5.5.5: same, 1.657) | accepted, 2,606 / 2,606, steel 1.020; 66 studs listed as outliers; 2 B |
| MOUNTAIN VIEW copy 7.433 (8f39034b) | steel 1.545, rejected; 2 C (v5.5.5: same) | accepted, 5,231 / 5,231, steel 1.007; 2 B |
| 19300_Henderson Hospital_1 7.618, no subm/ (e88c9467) | FileNotFoundError; 2 C | accepted, 63,909 / 63,909 (2,334 envelopes, 20,525 SDS2 bolts); 2 B |
| 2155-Young FAC 8.004, no subm/ (c316158b) | FileNotFoundError; 2 C | accepted, 31,958 / 31,958 (1,269 envelopes, 216 joists, 8,341 bolts); 2 B |
| Bishop HS 7.135, no subm/ (ea727761) | FileNotFoundError; 2 C | accepted, 12,322 / 12,322; 0 bolts. **The same 12,322 solids as the live stage-1 STEP**: only the label changes, the class stays 2 C |

**CSU against the fleet's current v5.5.5 (b555), which ships its own CSU fix:**

| converter | pieces written | read-back solids (valid) | skipped | steel |
|---|---|---|---|---|
| v5.5.5 | 14,506 | 14,510 (14,508) | 0 | 1.04 |
| v5.5.3 + patch | 14,434 | 14,438 (14,438) | **72** (`fallback_over_5x_source_weight`) | 1.03 |

The 72 are HSS6x4x3/8 and HSS4x4x3/8 pieces (`probe_csu.py`). Their piece-table records are broken:
- **L = 0 and SDS2 weight 0.08 / 0.63 lb**;
- their own face vertices span 52.6 x 6 x 4 in and 80.8 x 4 x 4 in, i.e. real members of about 100 lb.

The patch's new `>= 10x and +50 lb` clause compares the fallback with that corrupt weight and deletes them. v5.5.5 keeps
them as tagged profile fallbacks, and v5.5.3 never got that far (ValueError). This is the same mechanism as in 5.2.

## 3. Weight fixes on 12 DIFFERENT family-weight models (all class 2, none run by the author)

Columns: read-back solids (valid), b553 -> w553. Stud / rod family ratio (n >= 5), b553 -> w553. Family flags under the
current rule (b553 / w553), and under the proposed rule (w553). Exact pieces, b553 -> w553.

| job | read-back | stud / rod families | flags cur | flags new | exact pieces |
|---|---|---|---|---|---|
| traing mallesh 7.619 (e5dbfddd) | 379 -> 415 | WS 0.253 -> 0.961 | WS / - | - | 250 -> 286 |
| TEMP1 8.004 (150c2ec8) | 259 -> 265 | WS 0.715 -> 0.986 | WS / - | - | 212 -> 219 |
| TRAINING JOB 7.708 (48a0fd5c) | 591 -> 591 | RB 0.117 -> 1.000 | W,RB / W | - | 212 -> 263 |
| Misc_Training_Job 7.331 (63e3ea6c) | 1,517 -> 1,517 | RD 11.95 -> 1.000 | RD / - | - | 1,287 -> 1,304 |
| TRAINING_MISC-2 7.328 (0eb24540) | 1,187 -> 1,187 | BLT 1.467 -> 1.468 (one built bolt at 1.93x, **not fixed**) | BLT / BLT | - (built n = 1) | 1,074 -> 1,075 |
| YOUNG HARRIS 7.135 (18b12fc2) | 7,816 -> 7,816 | HS 3.55 -> 0.995 | HS / - | - | 5,025 -> 5,042 |
| 21006_MUHTF 7.613 (1b13daf8) | 1,644 -> 1,650 | TWS 0.022 -> 0.955, WS 0.247 -> 0.961 | TWS,WS / - | - | 1,252 -> 1,282 |
| CENTENE 7.516 (26aa7127) | 1,903 -> 1,903 | TWS 0.018 -> 0.959 | TWS / - | - | 914 -> 938 |
| VIOLET STREET 7.619 (322509b0) | 294 -> 334 | WS 0.262 -> 1.000 | WS / - | - | 136 -> 136 |
| FED_EX 7.720 (96655a9f) | 4,103 -> 4,097 | RB 0.498 -> 0.979, TWS 0.290 -> 0.956 | RB,TWS / - | - | 1,872 -> 2,069 |
| RAMESH 7.708 (91087bbe) | 1,368 -> 1,368 | RB 1.314 -> 1.004 | CP,ROUND,RB / CP,ROUND | - (CP 0.829 = the README's 1/8 floor-plate convention, listed as info) | 1,269 -> 1,271 |
| SDS_MISC_TRAINING 7.312 (0fb2c32a) | 4,261 -> 4,244 | RB 1.190 -> 1.007 | RB / - | - | 3,338 -> 3,373, **but 17 grating pieces lost (section 5.2)** |

Across these jobs:
- All read-back solids are valid.
- Placed pieces and SDS2 bolts are unchanged.
- Except on SDS_MISC_TRAINING, pieces written and solids written are unchanged too.
- Read-back leaf counts move because split stud segments merge. On Cytiva_A30 (eed128ca) the leaves fell from 4,013 to
  1,613, but the total read-back volume is unchanged (931,499.9 vs 931,496.2 in³).
- No converter-built family flag survives, except one bolt on TRAINING_MISC-2.

`probe_rod.json` covers every TURNED piece that takes the straight-rod path, over 33 fetched jobs (59 pieces). The patched
`rod_diameter` never preferred the name's diameter over the piece's own mesh, and every rod lands within 0.95-1.06 of SDS2's
weight (v5.5.3: TWS 0.009-0.033, RB 0.11-0.25).

## 4. Class-1 controls: 13 live class-1 jobs, IDENTICAL

The jobs cover versions 7.115 to 8.007 and include:
- 4d1080fd (RMC, 471 WS studs);
- 7846852e (56 HD);
- 0bf53d08 and 5b59df5f (BPL bent plates);
- 1f9bb631 (rails);
- 21b5d526 (RB);
- 1f26f9c0 (CHKD);
- the large affe4269 (3,008), d6dfde1c (2,157) and eae166ac (4,754).

v5.5.3 vs patched: read-back solids, validity, steel ratio, manifest class, stand-ins, skipped pieces and coordinator class
are all identical. The only change is RMC's WS ratio, 0.9999 -> 1.0001. All 13 stay class 1 under the proposed rule too.
Run time: controls rose by 0-10 %; the worst case among all jobs was +45 % (AGRANCLISSEMENT 76 -> 110 s).

## 5. Problems

### 5.1 The base is stale; the v5.5.3 patch breaks the fleet's current converter (blocking)
- converter.json switched to **v5.5.5** (sha 2a6e5b68…) at 05:11Z, one minute after the README was written.
- `patch -p1` on v5.5.4 or v5.5.5 rejects 7 hunks:
  - manifest.py: 1 hunk;
  - sds2job.py: 2 hunks (the CSU stale-record change, already shipped in v5.5.4);
  - to_step2.py: 4 hunks (the `brep_placed` gate, `_wpart`/`reset`, the `convert()` no-table head, the `track` call).
- The hunks that do apply reference `stats_nt`, `unidx`, `sdir` and `_wpart`, which are now undefined: NameError on every job.
- The patch must be rebased onto v5.5.5, and the rebase has to reconcile `_stock_match` with v5.5.4's `_section_ok`. v5.5.5
  already writes processing-Ted's L8x8x3/4 and YSIDRO's W360 pieces exactly (b555: 9 / 9 and 191 / 191 exact), but at
  0.794 and 0.843. What still lifts processing-Ted is excluding the disproved record from the tally, not new geometry.
- Binney still fails on v5.5.5, so the 7.243 hunk is still needed.
- worker.py (now b0de7f95) and build_index.py (now 93ebaa4e) changed after the shas named in the deliverable. Both of those
  patches still apply.

### 5.2 Regression: the new fallback gate deletes real parts (CSU HSS, bar grating)
The clause `w_ > 10*wt and w_ - wt > 50` trusts SDS2's recorded weight. Two cases where that fails:

**CSU 347cb74f.** 72 HSS members whose piece-table records are corrupt (L = 0, 0.08 / 0.63 lb) are deleted. The fleet's
v5.5.5 writes them (section 2). The old 1,000-lb floor protected exactly this case.

**Bar grating.** The clause has no grating exemption:
- SDS2 weighs GR/GT grating as the open mesh, and the converter's own `track()` skips `G[TR]\d` because the solid panel is
  about 7x that weight.
- On SDS_MISC_TRAINING_JOB (0fb2c32a), 17 of 67 grating pieces (GR1/8x68 ... GR1/8x164, GT1x10 7/8) that v5.5.3 wrote as
  tagged `bent_plate_fallback` stand-ins are now skipped (`fallback_over_5x_source_weight`).
- The piece-table slab fallback did not catch them either.
- Six other grating-heavy jobs were unaffected: DURGA TR, LINEAGE, RYAN, SAMPLE AC, Cytiva_A30, Spot Cooling, with 21-80
  grating stand-ins each.
- The live index holds about 41,000 GR/GT fallback stand-ins in 486 SDS2 rows, so the exposure is real even though the hit
  rate is low.

Fix:
- Exempt `G[TR]\d` from the new clause, as `track()` already does.
- Apply the clause only when SDS2's weight is consistent with the piece's own table size (L > 0, and weight within a
  factor of L x W x T or catalog x L).
- Otherwise drop the clause and keep only the MOUNTAIN VIEW behaviour of replacing the fallback with the piece-table slab,
  never skipping.

The README's "no pieces were lost" holds for its 13 jobs, not in general.

### 5.3 The no-piece-table (`brep_unindexed`) path
Placement decoding without `subm_idx` is correct. I checked it by hiding `subm/subm_idx` (a hard-link copy) on 3 jobs that
have one, then comparing with the normal patched run (`nxcmp.py`). Every indexed placement was reproduced:

| job | indexed placements matched (member + piece + origin) |
|---|---|
| RMC 7.135 | 2,833 / 2,833 |
| Mt Carmel 7.312 | 4,754 / 4,754 |
| MUHTF 7.613 | 1,376 / 1,376 |

The same comparison found the following.

a. **Read-back verification is defeated when a job holds only unindexed parts.** The product name
   `unindexed piece N [unindexed: <250 chars>]` is wrapped by the STEP writer onto the line after `PRODUCT(`.
   `verify_step.product_names()` then finds only the root product, so `load()` takes the "1 shape, 1 name" path. RMC with
   the table hidden read back as **"1 top-level shape; with solids: 1; BRep valid: 1" for 2,833 placed parts**, with the
   same bbox and total volume. Invalid parts would pass the gate: the whole compound counts as one item, within max(5, …).
   The 4 real data-3 jobs with piece files also have envelopes and bolts, so they take the leaf walk and report correctly
   (TATTIER: 59,265). The defect is latent. Fix: a short product name, or make `product_names` tolerate wrapped lines.

b. **No converter-duplicate check.** The indexed path skips identical (piece, origin, rotation) placements (FIX item 12;
   MUHTF: 5 skipped). The unindexed path writes them:
   - MUHTF: 5 coincident MC8x20 duplicates.
   - TATTIER: 6 same-piece / same-origin pairs, some across members (MISC 731 / BEAM 1159).
   - `converter_duplicates_skipped` stays 0, so the coordinator's `converter_duplicates` tag never fires.

c. **It places piece files the indexed path never writes.** These are files with no piece-table entry that member files
   still place:
   - Mt Carmel: +112 placements on MISC members (80 written, 32 not closed);
   - MUHTF: +59 on Concrete Slab / Wall members, plus the 5 duplicates.

   That is +1.7 % and +4.4 % parts. Concrete goes out as an unindexed "steel" B-rep, not through the concrete-prism rule.
   The parts are tagged and never class 1, but the output is not "the indexed output minus the names".

d. For the 16 jobs with no subm/ at all, stage 2 equals stage 1 plus SDS2's bolt records. Bishop HS has 0 bolts and keeps
   the identical 12,322 solids and class 2 C. The coordinator files their envelopes as `source_data_absent | undetailed
   members`, but the members are detailed and the backup simply lacks subm/. Bishop HS even has a full sibling copy,
   2b208687. `source_file_missing` would be the honest key; the coordinator patch maps only `unindexed_brep` to it.

### 5.4 The proposed grading rule disables most of the SDS2 class-1 weight check (owner decision)
- With the rule, the 5 % band is `(exact_sds2 + standin_sds2 + built_step) / total`. On real jobs "built" is a handful of
  pieces: AGRANCLISSEMENT has 4 built of 642 tallied, TRAINING_MISC-2 has 4 of 989. So the band no longer measures the
  model.
- Exact families get only an info line, outside 0.85-1.2. A job whose exact B-reps total 1.25x SDS2 would be **class 1**,
  because only the 0.75-1.3 class-3 band remains.
- "Exact" is not raw source data. It is the converter's own reconstruction (`brep.parse`/`brep.solid`, the subject of the
  fixer's loops_of spike / keyhole draft) plus the converter's decoded hole cuts. Errors there would no longer show.
- YSIDRO, TEST1 and SHOAL CREEK reach class 1 only through this rule.
- The per-family proofs (section 3b of the README) are sound as far as I checked; RAMESH's CP 0.829 matches the 1/8
  floor-plate figure. They argue for per-convention references (catalog lb/ft for W/WT/C, 0.100 in x developed area for
  deck, floor-plate psf for CHKD), not for dropping exact weight from the band.

### 5.5 `_stock_match` (rolled branch) accepts on extents alone and removes the piece from the ratio
- It accepts any closed B-rep whose extents match the table length x d x bf and whose weight is at most 1.1x the catalog.
  There is no lower bound.
- AGRANCLISSEMENT 713dae: 66 studs (254S89-144M) were accepted at **0.49x both the recorded and the section table's
  weight**. They are then dropped from the tally as `sds2_weight_outliers`.
- The README's "B-rep equals SDS2's own stock" is true for processing-Ted, but not what the code checks. The ~3.8 lb/ft
  cross-check from d / bf / lip / t lives in the README, not the code.
- On the rebase, use v5.5.4's `_section_ok` instead (area from the section's own dimensions, 0.75-1.3). Better still, keep
  validated outliers in the ratio against their computed reference rather than dropping them.

### 5.6 Smaller points
- MOUNTAIN VIEW: the gated BPL pieces became `piece_table_standin`, not skips, as described. AGRANCLISSEMENT keeps 2 skips;
  CSU 72 (section 2).
- Not re-run here; evidence from the author's logs only:
  - Nantucket: the t2w log shows 131,549 / 131,549 after the fix; the w553a log shows the base crash.
  - FORD HUB, IMS6, RCMS x2.
- Not verified by anyone: BOSK_E's read-back and BG PODIUM's run time. Neither of the author's runs (`j2/t2w/44e6352e…`,
  `j2/bgw`) has landed.
- No geometry is invented anywhere in the patch:
  - polygon heads use SDS2's own ring vertices;
  - rods are tagged and sized from the mesh, or from the name's standard diameter;
  - turned and unindexed solids are SDS2's closed B-reps;
  - the 7.243 layout is the module's documented one.
- Tag removals are backed by SDS2's closed, valid B-rep within 15 % (`turned_brep`) or by extents (`_stock_match`; see 5.5).

## 6. What to ship
1. Rebase onto v5.5.5 and re-test.
2. Fix the new `>= 10x and +50 lb` gate clause (section 5.2), or drop it:
   - exempt grating (`G[TR]\d`);
   - skip it when the piece-table record is unusable (L = 0, or a weight far below its own size);
   - never turn a piece into a skip where v5.5.3 / v5.5.5 wrote it.
3. For no-table jobs:
   - fix the product name or `product_names`;
   - add the dedup key to the unindexed loop;
   - skip piece files with no table entry, or report them separately;
   - send concrete through the concrete rule.
4. Replace `_stock_match`'s rolled branch with v5.5.4's `_section_ok`.
5. Ship `run_batch.parse_log` (last match) and the `DROP_LABELS` fix as they are. They are the most valuable part:
   - 31 jobs promote without re-conversion;
   - verified here on POLICE HQ (46 instances dropped), CCJ 48b139 and 9NOV_330PM (255 each). The last two are not the
     author's runs. In each case, instances that stay invalid after the round trip are dropped and reported, instead of
     sinking the whole stage 2 to members only.
6. Ship the stud / rod / anchor / bolt weight fixes (`_snap`, `_polygon_ring`, `turned_brep`, `rod_diameter` /
   `rod_length`) as they are. They hold on 12 family-weight jobs the author never ran, with no regression on 13 class-1 controls or on 6
   grating-heavy jobs.
7. Keep the coordinator rule as a separate owner decision. Do not count YSIDRO, TEST1 or SHOAL CREEK as converter lifts.
