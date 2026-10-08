# Adversarial review: ifc-verification-residue (session-3 deliverable)

**Verdict: CONFIRMED WITH CAVEATS.**

- **The SDS2 patch (`sds2_v5.4_sparse_layout_7243.diff`) holds up and is ready.** It also applies cleanly to the newest
  pipeline, v5.5.5.
- **The far pair holds on its own terms but is not ready to ship as is.** The pair is `ifc2step6_6.1.2_far_always.diff`
  plus `step_check_far_secondread_vs_fleet.diff`.
  - What holds: the class numbers reproduce on the fleet's current 6.1.4 (+2 class 1 on the Baylor files). On 19 other
    real models nothing is lost and nothing is fabricated.
  - What the deliverable does not disclose: the far-mode STEPs are **invalid when read in place** (OCC at the file's own
    coordinates) on every far model tested. Today's fleet output of the same models is valid in place.
  - The second-read grader also introduces **false invalid solids** on a file that is valid in place.
  - Details are in section 2. The lead has to decide on this with the numbers below; it is not "precision noise".

Everything ran on the agent boxes:

- **BOX-A** (i-0c694360a18d7759f, `/work/agentwork/ifc-verification-residue-review`).
  - Used the fleet worker's own `process()` with the coordinator's `classify_ifc` and live `rules.json` (the deliverable's
    `rc2.py` harness, unchanged).
  - Bases: fleet kit **6.1.4** (md5 6a87fe14, current since 21:37 local; the diff applies cleanly) and fleet
    `step_check.py` (md5 3f26ca81, unchanged).
- **BOX-C** (i-0d97427e58ca5ef28, `/work/agentwork/ifc-verification-residue-review/sds2`). Base: sds2-step-pipeline
  **v5.5.5** (newest; the fleet converter is v5.5.4).

Results are under `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue-review/`
(labels rvF, rvP, rvG, rvPF, rvF_big, rvP_big; `analysis/`; `sds2/`). Scripts are under
`s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue-review/`. The Mac only ran joins of
small JSON files. The scripts are also kept locally in `review/scripts/`.

Configurations (IFC):

| label | converter | grader |
|---|---|---|
| rvF | fleet 6.1.4 | fleet step_check (= fleet today) |
| rvP | 6.1.4 + far_always diff, `V6_FAR_ALWAYS=1` | second-read step_check (= the pair) |
| rvG | fleet 6.1.4 | second-read step_check (grader change alone) |
| rvPF | 6.1.4 + far_always, `V6_FAR_ALWAYS=1` | fleet step_check (converter change alone) |

Models (23, plus one 114 MB model):

- the 2 Baylor files the deliverable lifts
- 2 **other** Baylor files (not among its 14)
- 13 **non-Baylor** far-origin models: Marriott Bridge, BOBPM pack plant, TEST-1, Hickory, MIT SCC, World-Trade Tekla
  exports, ALM_WISD
- 6 **near-origin class-1 controls**
- the 114 MB **ALM_Baylor 07-28 copy** (557c5bc89f70; the deliverable only ran the 10-07 copy d713)

## 1. SDS2 `_sparse_try` 2,494-B layout for 7.221 / 7.233 / 7.243 / 7.253: CONFIRMED

- **Applies** to v5.5.5 (one hunk, exact context). `patch` is not installed on BOX-C, so it was applied with an
  exact-context applier; the result is byte-identical to `patch -p1` on the Mac.
- **Before/after on v5.5.5, stage 2 `--verify`, the jobs' own files:**

| job | v5.5.5 | v5.5.5 + patch |
|---|---|---|
| 6eeedc274302 100_Binney_Slab_Arch_Job | rc 1, `ValueError: too few members to calibrate (2)` | 164 exact SDS2 B-rep solids, 164/164 BRep-valid, 8.4 t = SDS2 8.4 t, **class 1 A** |
| a47a13079296 100_Binney_Slab_Job | rc 1, `member work points not found` | 1 solid (concrete_prism stand-in, tagged), valid, class 2 B |
| 58c969614e6f 100_Binney_Slab_Job | rc 1, `too few members (2)` | manifest class 3 C "no geometry in the source: 2 members ... 0 placed pieces" |
| 5eed44fe33ca Boylston_Job 7.221 | rc 1, `member work points not found` | 5,127 member envelopes (each tagged `[approx: member work-line envelope ...]`), 5,127/5,127 valid, class 3 C "members only" |

- **No fabricated geometry.**
  - In stage 2, piece placements come from the member files' own instance frames (`material_instances`, `to_step2.py`).
    The mem_idx layout only supplies the member type (MISC at 0x988), so Slab_Arch's 164 solids are SDS2's own piece
    B-reps where SDS2 put them.
  - Boylston's envelopes are built from the job's own section and end points. They are tagged and leave the job at
    class 3.
- **Different real models (layout survey).** I ran `calibrate()`, `sparse_layout()` and `read_members()`, base vs patch,
  on **all 35 data-3 jobs** of these four versions (lite fetch). The one job not run is SEAPORT, 1.5 GB lite; it
  calibrates on v5.5.0.
  - The patch changes the outcome of **exactly the 4 jobs above**.
  - The other 31 have byte-identical layouts and member lists. 30 of them calibrate; TEST100 cd4a4500 has no member
    files and fails identically.
- **Is 0x1D4 the right section field?**
  - The deliverable's calsurvey claim reproduces only when `piece_table` is importable. My first harness lacked it, and
    the heuristic alone then picks **0x1D8** on the small jobs: SAMPLE_JOB, 50B_Temp, Binney_Test x3, cpk, Baha_10_Roof_G.
  - With the converter's own main-piece agreement (each member's main-piece name) the field is unambiguous on all 28
    jobs with readable pieces: **0x1D4 agrees 0.74-1.00, 0x1D8 0.00-0.025**.
  - Boylston (no readable pieces): the heuristic scores 0x1D4 20.0 vs 0x1D8 0.0 (0/5,127 sections map at 0x1D8). Roll at
    0x1DA has 643 non-zero values in 32 distinct angles; 0x1DE is all zero. The layout is right.
  - `sec_check.jsonl` / `survey3.jsonl` are under `sds2/`.
- **Class-1 / class-2 controls, base vs patch: 5/5 identical** (STEP body md5, pieces CSV md5, class, read-back):
  98adc85b MASTER 7.233 (class 1 A), 9b72c7bc SAMPLE_JOB, 40e0ff87 50B_Temp, c84d4cc8 cpk, 2170ca1e Baha_Roof_C 7.233
  (2,944-B slots). TEST100 is identical class 3 C on both.
- **BG PODIUM on v5.5.3** (the deliverable's check run, still on BOX-C): the on-box log has "converted in 5774s",
  manifest class 2 B, steel 17,975 t vs 17,779 t (1.011). Confirmed. The 41.9 GB peak could not be checked:
  `/usr/bin/time` only writes it when the process exits, and the read-back is still running.

## 2. Far pair (6.1.2 far-mode port + second-read grader)

### 2a. Before/after and different models: the class claims REPRODUCE on 6.1.4

| group | model | rvF (fleet) | rvP (pair) | notes |
|---|---|---|---|---|
| Baylor, claimed | 4f6b8e2e9693 | 2 (L4 x4) | **1** | btp2_M x4: L4 surfaces -> L0 solid 461,828 mm3; ifcopenshell kernel mesh of the same product (local coords): closed, 462,038 mm3 (0.99955) |
| Baylor, claimed | 925e43c7b39a | 2 (open-surface x2, L1 x3) | **1** | bolts x2: F read-back 10,397 mm3 + open surfaces; P 48,417.5 mm3; kernel mesh 48,431 mm3 with 0 open edges (0.99972). The F `open_in_source` tag was a far-precision artefact: removed **with** proof |
| Baylor, new | e747269a560d | 1 (L1 2) | 1 (L0 231) | |
| Baylor, new | f582bf9375d8 | 2 (open-surface 16) | 2 (same 16) | open source shells stay tagged |
| far, class 1 | e7f6f3e68d0e, 59f3aa622092, 342f2352feaa, 77056eeaac10, bf768f1f03f3, aa1e8467bb71, 38a76d7c9e67 (Hickory, 248 MB) | 1 | 1 | P STEPs 0-67 % smaller (Hickory identical size: no shared geometry) |
| far, class 2 | ffd8d7272b6c, d528e0ccedbb, 9df308a46bf9 | 2 | 2 | |
| far, class 2 | c685065ec108 (Tekla) | 2 (1 invalid, L1 1) | 2 (0 invalid, L0) | |
| far, class 2 | c8689f1be0c1 (Tekla) | 2 (L2 4) | 2 (L2 3) | |
| far, class 2 | f451e1f2a811 ALM_WISD | 2 (L1 7, L2 3) | 2 (L1 0, L2 4) | 4 parts go **L0 -> L2** in P (see 2c) |
| near, class 1 | b0dd43ef3a3f, f2c1e8d84b30, 2446d6c85cc1, 3308dfc8659a, 58feb0df9ed8, 9322153b0255 | 1 | 1 | identical levels, solids, sizes |

- Gid join F -> P on all 23 models: **0 parts missing, 0 extra, 0 invalid in P's (translated) read-back.**
- The changed-level parts were checked against an independent reference: the ifcopenshell 0.9 kernel mesh of the same
  IFC product in local coordinates (26 parts; `analysis/chg1_FP.jsonl`).
  - 25 had a reference: P / kernel 0.9994-1.0005.
  - One approx-curved plate (925e p2_10) is at 0.9943, with the same volume in F and P.
  - c685065e's HSS chord has no reference (the kernel fails on it); its volume is the same in F and P within 3e-6.
- Unchanged-level parts differ by 0.1-0.3 % between F and P on curved or thin parts. The cause: shared local geometry in P
  vs expanded world-coordinate copies on a 0.01 mm grid in F. Against the census analytic volumes neither is
  systematically better (e747269a mean |dev| 0.00140 vs 0.00153; f582 0.00221 vs 0.00221; 925e 0.00130 vs 0.00130).
  Not fabrication.
- With `V6_FAR_ALWAYS` unset, the patched converter matches 6.1.4 on 8/8 models: multiset of CARTESIAN_POINTs,
  entity-type histogram and PRODUCT lines including tags. The files are **not byte-identical**, but 6.1.4 itself
  differs on 23,360 lines between two runs of the same input (non-deterministic entity order). So "off = byte-identical"
  should read "off = identical content".

### 2b. NOT DISCLOSED: far-mode output is invalid in place on 16/16 far models; fleet output is valid in place

Same STEPs, read in place by the fleet `step_check` with its far rule switched off (`inplace/step_check_inplace.py`;
`analysis/inplace_summary.txt`):

| model | 6.1.4 (rvF) in place: invalid / solids | 6.1.4+farall (rvP) in place: invalid / solids |
|---|---|---|
| e7f6f3e68d0e | 0 / 3 | 2 / 3 |
| 925e43c7b39a | 0 / 161 | 83 / 163 |
| 4f6b8e2e9693 | 0 / 154 | 119 / 158 |
| e747269a560d | 0 / 231 | 148 / 231 |
| 59f3aa622092 | 0 / 924 | 740 / 924 |
| f582bf9375d8 | 0 / 320 | 146 / 320 |
| 342f2352feaa | 0 / 2,089 | 948 / 2,089 |
| ffd8d7272b6c | 0 / 1,383 | 999 / 1,383 |
| bf768f1f03f3 | 0 / 675 | 88 / 675 |
| 77056eeaac10 | 0 / 3,013 | 1,688 / 3,013 |
| aa1e8467bb71 | 0 / 685 | 93 / 685 |
| d528e0ccedbb | 0 / 1,892 | 82 / 1,892 |
| 9df308a46bf9 | 0 / 1,982 | 77 / 1,982 |
| c685065ec108 | 1 / 5,635 | 465 / 5,635 |
| c8689f1be0c1 | 0 / 6,400 | 139 / 6,400 |
| f451e1f2a811 | 0 / 13,093 | **9,243** / 13,093 |
| **total** | **1 / 38,640** | **15,060 / 38,646** |

- The README and the diff comment call the in-place verdicts "OCC precision noise". These numbers show the in-place
  failures are **caused by far mode** keeping far instances as MAPPED_ITEMs (OCC applies the far transform). The fleet's
  6.1.4 expands far instances and verifies each one where it sits, which is the slug's own patch G. That output reads
  valid in place on the same models.
- With the pair, all these files are graded only on the km-shifted copy. Class-1 rows then get the coordinator's
  `valid_after_km_shift` warning.
  - That includes **aa1e8467 and e747269a, which are class 1 today without that warning and valid in place**. After the
    pair they would be class 1 with 93 / 148 solids invalid for any OCC consumer that reads them in place.
- The +2 class 1 therefore costs in-place validity on every far model. That trade-off is a lead / owner decision, and the
  deliverable did not present it.

### 2c. The second-read grader alone is not monotone (false invalid solids)

rvG vs rvF: the same 6.1.4 STEPs, second-read grader vs fleet grader.

- Identical on 21/23 models, Hickory included.
- **f451e1f2 ALM_WISD**: fleet grader 13,093 / 13,093 valid (MAPPED file, read in place). Second-read grader: **11
  invalid**.
  - The 11 are FACETED_BREP beams whose points are all far. The only near point is the context origin (0,0,0), so the copy
    is a true rigid translation.
  - They read valid in place and invalid after the km shift.
- **c685065e**: 2 valid-flag swaps (one part valid in place becomes invalid translated, and one the other way).
- The same effect is behind far mode's **L0 -> L2 flips on f451e1f2**: B-2111 and B-728 are among the 11. Their exact L0
  solid fails the shifted-copy check, so far mode writes the kernel triangle mesh (info tag, volume 1.0002-1.0005 of the
  kernel B-rep), although the L0 solid reads valid in place.
- So BRepCheck on the translated copy is not "the truth" either. Taking it **instead of** the in-place verdict creates
  false failures. Graded alone, f451e1f2 gets `invalid_solids:11`.
  - Any MAPPED far STEP that is not re-converted with far mode can get such false failures: reused or older outputs,
    or a deploy order where the grader ships first.

### 2d. Other checks

- **"Ship as a pair" is required.** Confirmed on different models: rvPF (far_always + fleet grader) demotes **7
  class-1 far models to class 2** with invalid_solids: e7f6f3 2, 59f3aa 740, 342f 948, 77056 1,688, bf768f 88, aa1e84 93,
  e747 148. This is a deploy-order hazard: the env flag alone silently breaks class 1.
- **Grader cost.** Hickory (248 MB non-MAPPED far STEP): fleet grader 898-942 s, second-read grader 1,418-1,653 s (+50-75 %).
  Peak tree RSS is 10.9 GB in both (the converter dominates).
- **Files over 1 GB.** `step_verify_big.py` has no far rule at all, so far STEPs over the read-back cap are graded in place.
  This is not new, but far mode's in-place-invalid instances would show up there as invalid solids.
- **Straddlers.** The far rule moves only points with max |coordinate| >= 10 km, so a model straddling 10 km would be
  torn. No index row straddles 1e7 mm (checked on `bbox_mm` of all IFC/DB1 rows), so the risk is theoretical.
- **Per-part pending** (no patch). The case.json files confirm f3852e4b (step_verify_big complete, 320,885/320,885
  valid, class 2) and f17e9439 (160,120/160,120, class 1).
- **L2 evidence.** `judge()` skips the volume check when `fr.nopen`; still true in 6.1.4 (`ifc2step6.py` ~2862).

### 2e. What would make the far fix safe (suggestion, not tested)

Keep 6.1.4's expanded, in-place-verified output, and only use the shifted-copy verdict as a fallback:

- **Converter.** Extend 6.1.4's last-resort far round to parts that place shared geometry (expand the instance, then
  verify the expanded copy shifted). Only parts that fail every in-place level would rely on it: 4f6b8e2e's 4 btp2_M and
  925e43c7's 2 bolts.
- **Grader.** `valid = in_place_valid or translated_valid` per root, not the translated verdict alone. That removes the
  false invalids of 2c and keeps today's in-place-valid files unchanged.

## 3. Long runs

### Hickory (38a76d7c9e67, 248 MB STEP, 52,996 parts, no shared geometry)

Class 1 in all four configurations, 52,996 / 52,996 valid. Grader time:

| configuration | step_check |
|---|---|
| fleet grader (rvF) | 942 s |
| fleet grader on far-mode output (rvPF) | 898 s |
| second-read grader (rvG) | 1,418 s |
| second-read grader on far-mode output (rvP) | 1,653 s |

### ALM_Baylor 07-28 copy (557c5bc89f70, 114 MB IFC, 9,220 parts; not run by the deliverable)

| | 6.1.4 + fleet grader (rvF_big) | pair (rvP_big) |
|---|---|---|
| class / issues | 2: invalid_solids:12, parts_without_solid:103 | 2: none (only blocker: 2 open-surface double-sided source surfaces) |
| levels | L0 9,045 / L1 53 / L2 19 / L4 103 | L0 9,219 / L1 1 |
| open-surface tags | 11 | 2 |
| STEP / converter + grading / peak tree RSS | 290.7 MB / 693 s / 21.7 GB | 120.3 MB / 506 s / 10.9 GB |
| read-back used for the grade | 10,533 / 10,545 valid | 10,648 / 10,648 valid (translated) |
| **in place** | **12 invalid / 10,545** | **7,144 invalid / 10,648** |

- Gid join: 0 parts missing, 0 extra.
- **All 175 changed parts were checked against the IFC kernel mesh** of the same product in local coordinates
  (`analysis/chg_big.jsonl`). Every kernel mesh is closed, with P / kernel volume 0.9994-1.0005:
  - L4-surface -> L0: 102 parts
  - L1 -> L0: 44 parts
  - L2 -> L0: 19 parts
  - L1 + open-surface -> L0: 9 parts
  - L4 -> L1: 1 part

  So the removed L4 / open-surface tags are removed **with** proof, and the deliverable's ALM claim reproduces on the
  other ALM copy.
- The cost is the same as in 2b: 67 % of the solids are invalid when the file is read in place, against 0.1 % today.

## 4. Bottom line

| item | verdict |
|---|---|
| SDS2 `sds2_v5.4_sparse_layout_7243.diff` | **confirmed, ship** |
| far pair: class lift, lost parts, fabrication, tag removal | confirmed: +2 class 1 on the Baylor files, the ALM tags drop; 0 lost / 0 extra parts; every changed part matches the IFC kernel reference |
| far pair: side effects | **not disclosed, blocking for a blind roll-out** (lead decision): in-place OCC validity drops from 99.99 % to 61 % over 16 far models, and to 33 % on ALM 07-28. Class-1 rows that are valid in place today (aa1e8467, e747269a) would carry `valid_after_km_shift`. The grader alone makes false invalids (f451e1f2: 11). The converter flag alone demotes 7 class-1 models. |
| per-part pending, L2 evidence | confirmed (no patch) |

Cleanup: my BOX-A / BOX-C work dirs were removed after the uploads; nothing else was touched; nothing was published.
