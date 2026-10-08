# Adversarial review: sds2-pieces-not-built

Reviewer run on 2026-10-02 from 07:00Z to 10:00Z. All compute ran on BOX-C i-0d97427e58ca5ef28.

- **Box workdir:** `/work/agentwork/sds2-pieces-not-built-review/`.
- **Raw results:** `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-pieces-not-built-review/`
  (`ab/`, `replay/`, `replay_placed/`, `nestscan/`).
- **Local copies:** compare JSON, nested-body list, per-job table and the scripts, in `review/` next to this file.

**Verdict: refuted as "ready".** Most of the patch is sound, and the headline win reproduces. But four defects block
a merge as it stands:

1. `_nest_voids()` cuts cavities into exact SDS2 pieces and reference parts where the source stores solid,
   overlapping bodies. This is fabricated geometry, and it changes no tag or class.
2. In the author's own FGBVF run, the patched manifest is class 0 broken with 3 parts dropped. v5.5.3 gives class 2 R
   there. The README reports FGBVF as "0 skipped".
3. `source_piece_has_no_geometry` labels parametric clevis records as "the job holds no geometry". With the grader
   diff that removes a converter flag without proof.
4. The base claim is false. v5.5.4, v5.5.5 and v5.5.6 were already published, and 4 hunks fail on v5.5.6.

Each of these has a small fix (§3). With them, the patch should be acceptable.

## 1. What was run

1. **Patch application (`git apply`):**
   - The v5.5.3 diff applies cleanly to v5.5.3 (706e1289…).
   - The v5.4 diff applies cleanly to v5.4 (bf4a07fc…).
   - The applied tree equals the author's box tree `v553s` in code; 3 comment lines differ.
   - **It does not apply to v5.5.6** (ef1952bf…): `to_step2.py` hunks #1, #3, #6 and #8 are rejected.
2. **A/B with the fleet command** (`sds2_to_step.py <job> -o X --stage 2 --verify`, v5.5.3 vs v5.5.3 + patch) on
   **37 real jobs. Only jfkf, THERMOFISHER and A-Practice overlap with the author's 33.**
   - 9 live class-1 controls.
   - 6 reference lift candidates.
   - 14 pieces-not-built steel jobs.
   - 7 class-2 regression jobs with no pieces-not-built flag (SDS2 7.1 / 7.2 / 7.3 / 7.4 / 7.6 / 7.7), plus
     American Prep.
   - The compare covers class, reasons, counts, skip reasons, read-back valid / solids, steel / SDS2 ratio, read-back
     total volume, and every `_pieces.csv` row (member / piece / inst → builder).
3. **Piece-level replay** of `brep.solid()`, old vs new, on the jobs' own piece files.
   - `replay/`: 1,500 random files per job.
   - `replay_placed/`: every placed or skipped piece of 37 jobs, 52.5k pieces.
   - For every newly closed solid, its area is compared with the area of SDS2's own kept faces. If they differ, faces
     were added or removed.
4. **Nested-body scan** (`nestscan/`): 154 job folders on BOX-C, up to 3,000 piece files each, 357,301 files in all.
   - Covers every piece with a closed body inside another body's box.
   - Records each body's signed volume from SDS2's own winding: negative means stored inward, i.e. a void.
   - Records whether the patched `solid()` changes the piece's volume.

## 2. What holds

- **jfkf: class 2 R → 1 R, reproduced.** Read-back is 694 / 694 solids, all valid; v5.5.3 gives 70 solids + 624 face
  sets.
  - All 47 unique parts behind it are newly closed solids.
  - For every one, the area equals SDS2's kept faces exactly (ratio 1.0000). The fix only drops zero-area and
    repeated faces; nothing is added.
- **All 83 newly closed solids in the placed-piece replay** (jfkf, nhvb, HJ, P-01, CAPITOL, …) have area ratio 1.0000.
- **Class-1 controls identical** (2 R, 6 A, and PROCTOR_GAMBLE, which is class 1 only on v5.5.6.1): same class, rows,
  read-back, steel ratio, and read-back volume to 0.1 in3.
- **Class-2 regression jobs identical:** MiddleSchoolF, P454, CENTRAL OHIO, JH Camp, SKYLINE and Loudoun.
- **No `_pieces.csv` row of v5.5.3 is lost** in any of the 37 jobs.
- **Only one solid "lost" in the replay, and it was garbage:** nhvb part 1478. v5.5.3's `drop_covered()` reduced its
  40 faces to a 0.0014 in3 sliver. With the patch it is written as an open surface. That is an improvement.
- **Reproduced:**
  - THERMOFISHER: 58 → 0.
  - A-Practice: SH exact, 1 → 0.
  - OKANA: `126x82 7/8` exact, 22 → 21, with an unchanged ratio.
  - EDWARDS AFB: W24x76 → tagged profile, `rolled_sds2_weight_outliers` 1.
  - vgh: 71 → 0 (single triangles).
  - HJ: 1 → 0, +148 solids.
  - P-01: 8 → 0 reference skips, face sets 163 → 0.
  - nhvb: +20 closed solids.
- **Not in the README:** in CAPITOL, 24 joist placements (32LH / 24LH / 10K1) go from the tagged
  `derived_from_designation` stand-in to SDS2's own B-rep, `exact_brep`. These are repeated faces dropped, area ratio
  1.0, weight-checked.
- **Correct source-gap relabels:**
  - DALLAS LOVE FIELD (3b8778): 239 → `source_piece_file_missing`.
  - Boston Garden: FL0x0 216-byte stubs.
  - TRAIS: W shapes with L = 0 and flat faces.
- **State_Reno (author's run):** 29,182 → 35,974 parts written in the same budget.

## 3. Problems found

### 3.1 `_nest_voids()` fabricates cavities (exact pieces and reference parts)

`_nest_voids()` makes any closed body that lies inside another closed body of the same piece a void, or cuts it out.
It never looks at how SDS2 orients that inner body.

**SDS2's genuine hollow pieces store the inner wall inward** (negative signed volume): A-Practice SH 615, 19156_610
SH 2923, and the main inner wall of the BPV STAIR SH pieces. The voids there are right, and SDS2's weight confirms
them.

**The nested-body scan shows those are the minority.** Of the 40 sampled pieces whose volume the patch changes:

- 34 have the inner body stored **outward**, i.e. as solid material:
  - State_Reno ×2 jobs: 16 pieces.
  - American Prep: 5.
  - archthree: 3, ff: 3, hjj: 3.
  - P-01: 2, P-02: 2.
- 4 are mixed (BPV STAIR SH).
- Only 2 are inward: the README's own examples.

**End-to-end evidence from the A/B runs:**

- **American Prep 08a6f8, exact joists 22K9 / 28K9 (pieces 1009-1014, 7 placements, `exact_brep` in both runs):**
  - SDS2 stores each web member overlapping its neighbour. For example, vertical web body 15 (+18.7 in3) lies
    entirely inside diagonal web body 24 (+25.4 in3).
  - The patch turns it into a void.
  - Read-back solids drop 14,370 → 14,356, read-back volume drops by 106.7 in3 (= 7 × 15.2), and family '?' drops
    by 30 lb.
  - Rows, builders and class are unchanged. The pieces are still tagged exact, now with holes inside the webs that
    SDS2 does not have. The 0.6-1.6 weight check cannot see a 0.09 % change.
- **P-01 (reference model, no weight check at all):**
  - Part 742: two outward bodies, 63 in long. The volume goes 1,393.5 → 714.5 in3 (-49 %).
  - Part 634: an outward body is cut out as a pocket (area ratio 0.966).
  - The job's read-back volume falls by 2,221 in3, even though 8 more parts are written and 163 face sets become
    solids.
- **Two README claims do not hold here:** "The result is SDS2's exact geometry, validated by SDS2's own weight" and
  "No face is added or moved". Reference parts have no weight to check against, and the cut / void changes faces.

**Fix:** take a body as a void only if its source signed volume has the opposite sign to its parent's. Compute it with
`bodies()` and the stored winding, as `nestscan.py` does. That keeps A-Practice, 19156_610 and the BPV inner wall, and
leaves every outward body unchanged.

### 3.2 FGBVF regresses to class 0 broken (author's own run, not reported)

The author's `ab553/v553q/FGBVF_c2e2f4` is the tested tree. Both FGBVF runs hit the 10,800 s harness timeout
(rc = 124) during the second read-back, so neither final read-back finished.

| run | read-back repair pass 1 | repair outcome | stage-2 manifest |
|---|---|---|---|
| v5.5.3 | 16 invalid parts | 16 placed copies | class 2 R |
| patched | 19 invalid parts | reference pieces 1316 / 1320 / 1321 dropped as `exact_solid_invalid_at_placement` | **class 0 broken** ("3 of 3 placed steel pieces not built > 5 %"); `reference_parts` 34,660 of 34,663 |

- In v5.5.3 those 3 parts were written (`reference_brep`).
- The README instead reports "34,663 of 34,663 placements written, 0 skipped" for FGBVF, which is a lift candidate.
- The 3-of-3 rule counting reference parts as steel is a pre-existing classifier quirk. The patch is what triggers it
  here, and 3 parts are lost.
- **Needs:** a full rerun with a longer timeout, and the cause of the 3 invalid placements. They are probably newly
  closed or nested solids that fail once placed.

### 3.3 `source_piece_has_no_geometry` mislabels parametric clevis records

The test is: the parse fails and there are fewer than 4 vertex records. Clevis pieces are stored as a boost
`serialization::archive` record of dimension doubles, including 2π arc values, and the test matches them.

| job | piece | placements | file size | section | SDS2 weight |
|---|---|---:|---|---|---|
| PSU_BNR (author's set) | CV6 | 69 | 817 / 1,009 bytes | 1414 | 26 lb |
| Valley Health Mob | CV2 | 10 | 1,009 bytes | 1408 | 1.0 lb |
| PNW Freezer | #3 CLEVIS | 58 | 1,009 bytes | | |

- The manifest says the job holds no geometry. It does; the converter cannot decode this record type.
- With `optional_grader_build_index.diff`, these move from `converter_feature | sds2 pieces not built` to
  `source_data_absent`, without proof.
- **Fix:** restrict this reason to empty stubs, e.g. ≤ 261 bytes or no doubles beyond the identity frame. Keep
  records with `serialization::archive`, a section, or a weight > 0 as `no_usable_special_geometry`.
- Also unproven: the CERTAINTEED `120DLH20` joists (flat faces, table T = 144) labelled `source_piece_zero_size`.
  They are joists, not zero-size pieces.

### 3.4 The base claim is false; the patch does not apply to the current release

- v5.5.4 (04:54Z), v5.5.5 (05:00Z) and v5.5.6 (05:33Z) were published before this deliverable: diffs 06:11Z,
  README 06:57Z. Live models are already graded as v5.5.6.1.
- On v5.5.6, 4 `to_step2.py` hunks are rejected.
- v5.5.4+ overlaps the patch:
  - `_section_ok` / `VALIDATED_BY_SECTION` takes a rolled B-rep whose SDS2 weight disagrees. That overlaps §2.6, and
    gives an exact piece rather than a tagged profile.
  - `UNVALIDATED` / `exact_brep_unvalidated` tags unvalidated B-reps.
  - The open-rim `brep_open_surface` path.
- The v5.4 port matches the task's named base. But a merge needs a manual rebase onto v5.5.6 and a re-test there.

### 3.5 Table-empty B-reps are written as plain exact (policy mismatch)

- `_fits_own_record()` returns True for every kind except round bars and plates with a table thickness.
- THERMOFISHER and Henderson FB0x0 pieces (kind "other", L = W = T = wt = 0) are therefore written as `exact_brep`
  with no check against the record.
- The geometry is the source's own, so nothing is fabricated. But v5.5.4+ tags unvalidated stored B-reps as
  `exact_brep_unvalidated` (class 2). Align with that when rebasing.

### 3.6 Smaller inaccuracies in the README

- **"Every read-back is valid":** State_Reno ends class 0 broken (2 invalid after read-back) on both v5.5.3 and the
  patch.
- **Lift candidates that stay class 0 broken on both**, with a pieces-not-built entry
  (`exact_solid_invalid_at_placement`):
  - I1SD (ee874b) and P-01 (bee88c), both of the 57.
  - The projection counts them among the 52 that "lose the flag".
- **§2.6:** when a rolled piece has no geometry (`nominal = True`), V is the table-length box, so "the vertices span
  that length" is circular. Such pieces are still tagged approx, so this is minor.

## 4. Per-job A/B (BOX-C, v5.5.3 → v5.5.3 + patch)

Δ read-back volume is the `--verify` total volume, patched minus v5.5.3. "rows lost" counts v5.5.3 `_pieces.csv`
rows missing with the patch.

**Class-1 controls (live class 1; PROCTOR_GAMBLE is class 1 only on v5.5.6.1)**

| job | class | skipped | exact/approx or ref parts | read-back valid/solids | steel/SDS2 | Δ read-back volume in3 | rows lost |
|---|---|---|---|---|---|---|---|
| cddd_6ddc2a | 1R → 1R | 0 → 0 | ref 2 (open 0, fsets 0) → ref 2 (open 0, fsets 0) | 2/2 → 2/2 | None → None | +0 | 0 |
| ddfdf_bfdd9a | 1R → 1R | 0 → 0 | ref 2 (open 0, fsets 0) → ref 2 (open 0, fsets 0) | 2/2 → 2/2 | None → None | +0 | 0 |
| c1A_a_04e569 | 1A → 1A | 0 → 0 | 74/0 → 74/0 | 74/74 → 74/74 | 0.9991 → 0.9991 | +0 | 0 |
| c1A_b_20b067 | 1A → 1A | 0 → 0 | 2/0 → 2/0 | 2/2 → 2/2 | 1.0238 → 1.0238 | +0 | 0 |
| c1A_e_2d7f40 | 1A → 1A | 0 → 0 | 17/0 → 17/0 | 17/17 → 17/17 | 0.9751 → 0.9751 | +0 | 0 |
| 1086-LA_Technology_Job_f44e68 | 1A → 1A | 0 → 0 | 1453/0 → 1453/0 | 1893/1893 → 1893/1893 | 1.0218 → 1.0218 | +0 | 0 |
| BHSW_JOB_V3.313_-_Single_Detail_c64eb9 | 1A → 1A | 0 → 0 | 16/0 → 16/0 | 16/16 → 16/16 | 1.0296 → 1.0296 | +0 | 0 |
| c1C_a_59f1b3 | 1A → 1A | 0 → 0 | 997/0 → 997/0 | 997/997 → 997/997 | 1.019 → 1.019 | +0 | 0 |
| PROCTOR_GAMBLE_JOB_VOID_87772f | 2B → 2B | 0 → 0 | 921/116 → 921/116 | 1038/1038 → 1038/1038 | 1.0224 → 1.0224 | +0 | 0 |

**Reference lift candidates**

| job | class | skipped | exact/approx or ref parts | read-back valid/solids | steel/SDS2 | Δ read-back volume in3 | rows lost |
|---|---|---|---|---|---|---|---|
| jfkf_23c107 | 2R → 1R | 0 → 0 | ref 694 (open 624, fsets 624) → ref 694 (open 0, fsets 0) | 694/70 → 694/694 | None → None | +11,192,649,115 | 0 |
| nhvb_5b6ccf | 2R → 2R | 0 → 0 | ref 2827 (open 238, fsets 0) → ref 2827 (open 224, fsets 0) | 3172/2934 → 3178/2954 | None → None | +71,916,765 | 0 |
| P-01_bee88c | 0x → 0x | 9 (ref_no_closed 8, invalid_at_placement 1) → 1 (invalid_at_placement 1) | ref 2420 (open 826, fsets 163) → ref 2428 (open 824, fsets 0) | 1/1 → 1/1 | None → None | -2,221 | 0 |
| I1SD_ee874b | 0x → 0x | 2 (invalid_at_placement 2) → 2 (invalid_at_placement 2) | ref 3310 (open 3218, fsets 0) → ref 3310 (open 3218, fsets 0) | 3386/166 → 3386/166 | None → None | +0 | 0 |
| vgh_6d1a93 | 2R → 2R | 71 (ref_no_closed 71) → 0 | ref 4427 (open 4411, fsets 0) → ref 4498 (open 4482, fsets 0) | 4719/308 → 4790/308 | None → None | +0 | 0 |
| HJ_49ba71 | 2R → 2R | 1 (ref_no_closed 1) → 0 | ref 18252 (open 6724, fsets 7) → ref 18253 (open 6689, fsets 5) | 24989/18265 → 25102/18413 | None → None | +1,062,855 | 0 |

**Pieces-not-built steel jobs**

| job | class | skipped | exact/approx or ref parts | read-back valid/solids | steel/SDS2 | Δ read-back volume in3 | rows lost |
|---|---|---|---|---|---|---|---|
| 18011_PNW_Freezer_J_438d3c | 2B → 2B | 58 (no_usable 58) → 58 (src_has_no_geometry 58) | 10972/2405 → 10972/2405 | 47406/47406 → 47406/47406 | 1.0178 → 1.0178 | +0 | 0 |
| 1811_K-12_EDWARDS_AFB_BUILDING_A_JOB_1 | 0x → 0x | 1 (over_5x 1) → 0 | 16835/2003 → 16835/2004 | 52574/52578 → 52575/52579 | 1.0105 → 1.0105 | +7,666 | 0 |
| 2259-OKANA_Resort-IWP_JOB_ABMBACKUP_1d | 2B → 2B | 22 (over_5x 4, no_usable 18) → 21 (over_5x 3, no_usable 18) | 15961/543 → 15962/543 | 56742/56742 → 56743/56743 | 1.0292 → 1.0292 | +221,073 | 0 |
| A-Practice_Job_1cd870 | 2B → 2B | 1 (over_5x 1) → 0 | 1124/160 → 1125/160 | 6865/6865 → 6866/6866 | 1.0032 → 1.0031 | +19,485 | 0 |
| Boston_Garden_Below_Grade_Job_24d43c | 2B → 2B | 4 (no_usable 4) → 4 (src_has_no_geometry 4) | 376/2744 → 376/2744 | 8076/8076 → 8076/8076 | 1.0007 → 1.0007 | +0 | 0 |
| CAPITOL_DISTRIBUTING_JOB_405007 | 2B → 2B | 26 (no_usable 26) → 26 (src_has_no_geometry 26) | 19285/798 → 19309/774 | 130715/130715 → 132408/132408 | 1.0064 → 1.0063 | +55,564 | 0 |
| CERTAINTEED_JOB_IFC_model_0708f0 | 2B → 2B | 4 (builder_failed 4) → 4 (src_zero_size 4) | 1645/236 → 1645/236 | 4566/4566 → 4566/4566 | 0.9832 → 0.9832 | +0 | 0 |
| Merck_Job_29Oct13_3c6a8b | 2B → 2B | 27 (over_5x 27) → 27 (over_5x 27) | 854/254 → 854/254 | 2419/2419 → 2419/2419 | 1.0242 → 1.0242 | +0 | 0 |
| Misc_1144_15th_Street_Job_131406 | 2B → 2B | 46 (over_5x 46) → 46 (over_5x 46) | 5663/941 → 5663/941 | 7642/7642 → 7642/7642 | 1.0176 → 1.0176 | +0 | 0 |
| Peterson_locker_bldg._and_pool_job_049 | 2B → 2B | 9 (no_usable 9) → 9 (no_usable 9) | 4470/496 → 4470/496 | 8841/8841 → 8841/8841 | 1.0085 → 1.0085 | +0 | 0 |
| THERMOFISHER_JOB_bff8f8 | 2B → 2B | 58 (no_usable 58) → 0 | 11143/4551 → 11201/4551 | 34277/34277 → 34335/34335 | 1.0082 → 1.0082 | +12,691 | 0 |
| TRAIS_JOB_22e6cd | 2B → 2B | 5 (builder_failed 5) → 5 (src_zero_size 5) | 0/14981 → 0/14981 | 14981/14981 → 14981/14981 | None → None | +0 | 0 |
| UOM_Union_Renovation_BP5_Misc_JOB_25-0 | 2B → 2B | 38 (over_5x 38) → 38 (over_5x 38) | 11079/2153 → 11079/2153 | 45233/45233 → 45233/45233 | 1.0072 → 1.0072 | +0 | 0 |
| Valley_Health_Mob_08097e | 2B → 2B | 10 (no_usable 10) → 10 (src_has_no_geometry 10) | 3911/712 → 3911/712 | 7049/7049 → 7049/7049 | 1.0242 → 1.0242 | +0 | 0 |
| pnb239_3b8778 | 2B → 2B | 239 (no_usable 239) → 239 (src_file_missing 239) | 1122/4004 → 1122/4004 | 17129/17129 → 17129/17129 | 1.0152 → 1.0152 | +0 | 0 |

**Class-2 regression controls (no pieces-not-built flag) + American Prep**

| job | class | skipped | exact/approx or ref parts | read-back valid/solids | steel/SDS2 | Δ read-back volume in3 | rows lost |
|---|---|---|---|---|---|---|---|
| MiddleSchoolF_Job_03d1b7 | 2B → 2B | 0 → 0 | 19688/34 → 19688/34 | 111939/111939 → 111939/111939 | 1.0245 → 1.0245 | +0 | 0 |
| P454_JOB_1ea0ad | 2B → 2B | 0 → 0 | 14859/58 → 14859/58 | 109866/109866 → 109866/109866 | 1.0142 → 1.0142 | +0 | 0 |
| CENTRAL__OHIO_JOB_e08110 | 2B → 2B | 0 → 0 | 18239/1571 → 18239/1571 | 41138/41138 → 41138/41138 | 1.0063 → 1.0063 | +0 | 0 |
| JH_Camp_ID_Fan_Job_6c474f | 2B → 2B | 0 → 0 | 6538/1254 → 6538/1254 | 38764/38764 → 38764/38764 | 1.0074 → 1.0074 | +0 | 0 |
| BACK_UP_SKYLINE_062118_70cb34 | 0x → 0x | 0 → 0 | 4223/532 → 4223/532 | 25793/25795 → 25793/25795 | 1.0389 → 1.0389 | +0 | 0 |
| Loudoun_ADMIN_WTP_JOB_912562 | 0x → 0x | 0 → 0 | 5777/339 → 5777/339 | 68842/68843 → 68842/68843 | 1.0275 → 1.0275 | +0 | 0 |
| 024_1901_BPV_STAIR_80383b | 0x → 0x | 0 → 0 | 7005/1789 → 7007/1787 | 53134/53136 → 53136/53138 | 1.0148 → 1.0148 | -112 | 0 |
| 02-03-20_19189_American_Prep_Misc_JOB_ | 2B → 2B | 0 → 0 | 7341/2163 → 7341/2163 | 14370/14370 → 14356/14356 | 1.0111 → 1.011 | -107 | 0 |


## 5. Housekeeping

- Every review job on BOX-C has finished: `AB_DONE`, `AB2_DONE`, `AB3_DONE`, `REPLAY_DONE`, `REPLAY_PLACED_DONE` and
  `NEST_DONE` are all written.
- The `annotationprod-publish` SSO session expired at about 09:00Z. Since then:
  - Results were read through the `bim` profile.
  - The fetched job folders under `/work/agentwork/sds2-pieces-not-built-review/jobs` could not be removed. They
    still need deleting.
  - Nothing was uploaded to the `annotationprod` pfix prefix.
- No source, base zip or published converter was modified.
