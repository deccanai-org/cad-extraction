# Completeness critic: IFC, Tekla (DB1) and SDS2 audits of Zenitude-data-3 conversions

Snapshot: live state 2026-10-02 00:57-01:10Z (conv_status 00:57:04Z, index 00:57Z, final/auto_status 00:59:41Z, claims ~01:10Z).
The audits it reviews were taken at: IFC 00:32-00:40Z, Tekla 00:09Z, SDS2 00:22-00:49Z.
Scratch scripts are in `_audit/critic/`. The box spot-check output is at
`s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/critic-z3/openings_spotcheck.json` (BOX-A; work dir removed).

---------------------------------------------------------------------------------------------------------------------------------

## 1. Spot-checks against live data (13 checks)

| # | Audit claim | How I checked | Result |
|---|---|---|---|
| 1 | IFC: class-1 STEPs of SDS/2 faceted bodies have holes/copes uncut | **BOX-A**, my own script (volume-set match: ifcopenshell cut and uncut kernel volumes vs every OCC solid volume in the STEP). Ran on 3 live class-1 s6/6.0.1 models: 14e58e8a, 325e2cd3, 050de81b | **CONFIRMED.** 76 of 76 measurable products match only the uncut volume; 0 match the cut volume. Example: 0vqGx9f8 IfcPlate f491_2, cut 209,102 mm3 vs uncut 221,225 mm3; the STEP holds the uncut solid. |
| 2 | Same flaw, scale (1,220 / 1,179 models) | Re-joined the auditor's scan.jsonl.gz to the 00:57Z index | **CONFIRMED.** Of 1,807 live class-1 models, 1,226 have transcoded products with openings and 1,185 have at least 1 sampled part equal to the uncut volume. **1,039 have an unambiguous uncut sample (opening effect ≥ 0.5%)**: reused disk-1/2 399, z3-a 279, s6 351, s6+x1 6, data-4 1, s6.1 3 (the s6.1 ones were scanned before their re-run). |
| 3 | ifc2step5 transcodes faceted bodies without openings, and data-4 used it too | Read the code of z3 ifc2step5 and data-4 `_control/conv/ifc/ifc2step5.py` | **CONFIRMED.** Openings appear only in SKIP_TYPES; run_transcode never subtracts them. data-4's kit holds ifc2step5 only. Its **11,099 data-4 IFC STEPs** and the **14,652 Disk-1/2 IFC STEPs** in dataset/main come from writers with this behaviour. |
| 4 | IFC: 1,376 class-1 models have no volume check | Index | **CONFIRMED (now 1,382 of 1,807).** Only 289,566 of 2,072,623 class-1 parts (14.0%) are volume-checked. 0 models of 250 MB or more are class 1. |
| 5 | The IFC re-run rule never revisits class 1 | `_control/z3conv/coord/reconvert.json` | **CONFIRMED.** The ifc rule `+s6.1` has classes [2, 3]. |
| 6 | DB1: KeyError 's' in db1bolts.catalog_geometry (fix not deployed) | Live result `db1/results/7c68f0c9874e….json` plus the deployed kit | **CONFIRMED, still live under code l at 00:49:48Z.** Trace: db1bolts.py:98, `b['s']`. Deployed db1bolts.py md5 5846a3bf has no 'ambiguous' guard. Under code l, 3585d86a380d and 48e010c8ec25 also hit `convert_error` and c114f84dc319 hit `step_kernel_crash`. All 3 read status ok, code l, "earlier STEP kept". 3585d86a380d and 48e010c8ec25 still serve the **code-h** STEP. |
| 7 | DB1: grader best-of keeps the worse reused/Windows STEP (10 models) | Index plus 93 DB1 results | **CONFIRMED (now 12).** Examples: 0dd3da934923, 291547d3c10f, 3c6b9781f5d0, 4518a79a995b, 5b33936fcd1e, 6b87b724b554, 7c82c44be6c7, 7d7b67181db9, 8ebd3570ad53, c8d753af8630, ea1a25eb296b, fd302a00f03f. The cause is score = (class, number of issue+standin+need entries) in build_index `once()`. |
| 8 | SDS2: 41 of 44 class-1 models are reused v4 with no manifest | Index | **CONFIRMED.** 40 come from disk-2-run-2 and 1 from data-4, all with manifest_class null. |
| 9 | SDS2: b244541c is class 3 although its manifest says class 1 A | Index | **CONFIRMED.** member_coverage 0.1166 (v5.1), manifest class 1 A ("all pieces exact"). |
| 10 | SDS2: false out-of-memory class 3 overwrote published STEPs | Index plus S3 listing | **CONFIRMED (now 12 class-3 out-of-memory).** Published v5.1 STEPs exist for ff442ef1 MELBOURNE (508,487,369 B), 556b8979 l-arch (32,219,003 B) and bee88c67 P-01 (1,202,895,399 B), yet the index shows step_key None, class 3. |
| 11 | SDS2: superseded converters keep claiming first-time jobs | 571 claim files (~01:10Z) | **CONFIRMED and worse.** Fresh claims: v5.1 148, v5.3 72, v5.4 68, v5.2 13, v5 3, against v5.4.1 162. |
| 12 | IFC: 6.0.1-started workers keep running after the 6.1 swap | IFC claims (~01:10Z) | **CONFIRMED.** 25 fresh claims are still labelled '+s6' or '+s6+x1', against 37 labelled '+s6.1+x1'. |
| 13 | IFC: all-zero sources are a proven source limit | Ranged GET of 6250be71ec4f, bytes 0-255 and 4,000,000-4,000,255 | **CONFIRMED.** All NUL. The data-3 7z member reaches this content through sha identity. |
| 14 | SDS2: "main-member bolt holes missing in **every** SDS2 version" | Independent stream `_fast/sds2-recall-nc1/results/report_interim4.md` (00:54Z, 110 jobs, NC1 hole lists written by SDS2) | **CORRECTED, overstated.** NC1 hole recall on rolled main members: v5.1 0.868, v5.2 0.869, v5.3 0.808, v4c 0.498. The gap is partial and depends on version and label: v4c 7.3xx 0.361, v4c 7.7xx 0.168, v5.3 7.4xx 0.328, v5.3 8.0xx 0 of 193. |
| 15 | Tekla: "db1bolts2 (the 7.5x-9.x bolt writer) is not deployed" | Deployed `_control/z3conv/db1/` (worker CODE l) and the history | **STALE.** Code k (00:20Z) deployed kit_v2 / db1bolts2 for 7.5x-8.x. The auditor's own validation was 408 of 6,696 groups joined on 8.07 and 0 on 7.98, yet it went live. No data-3 7.30-9.21 row has a k/l result yet: all 9 still serve code-j or reused STEPs. Bolts are going out unvalidated. |
| 16 | IFC: "final/hold present, final pass not started" | rules.json, `_state/conv/final/` | **STALE.** `auto_final: true` since 00:45Z (lead), and there is no hold object. See gap G1. |

---------------------------------------------------------------------------------------------------------------------------------

## 2. Gaps that no audit reports (new, with evidence)

**G1. Auto-final can freeze known-false classes. Cross-pipeline, UNOWNED.**
- rules.json has `auto_final: true` (00:45Z). build_index starts the final pass by itself when pending, in-flight and *active* re-run targets are all 0.
- Paused rules (`sds2_paused`: the v5.2 class-2 rules and the v5.3 duplicate rule) are not counted as targets. So the final pass can start before the SDS2 class-2 re-runs ever resume.
- `final_jobs()` covers only ifc and db1, and only classes 1/2. It runs an IFC census refresh for parts_outside_volume_tolerance and an OCC read-back where none was done. SDS2 gets no final job, and nothing re-checks openings in class-1 STEPs.
- The final read-back calls `check_step` with RB_MAX 1 GB (grade/worker.py:25/71/85). So the 158 IFC and 1 DB1 STEPs of 1 GiB or more get **text-only checks again**; step_verify_big is not wired in. 58 SDS2 STEPs of 1 GiB or more are never re-read by the grader.
- Status at 00:59:41Z: drained false; open targets ifc 2,053, db1 77, sds2 74.

**G2. The grader-level best-of (reused vs fresh) hides v6 and v6.1 fixes in IFC too, not only in DB1. UNOWNED.**
- 90 IFC rows keep the reused ifc2step5 STEP although a fresh STEP exists: 80 s6, 3 s6+x1, **7 s6.1+x1 (openings cut)**. All are class 2 vs class 2, decided by the entry-count score.
  - Examples: 0933b1c14211 (reused, parts_without_solid 14,864), 1863ede91c49, 39a8bf5323c8. s6.1 losers: 4945991e, 6c7b8e80, 95456a17, a80c9618, af131b3b, c768a1ba, dc44ff6d.
- Those 7 rows keep converter_code None, so they stay "open targets" of the s6.1 rule forever. Either the final pass can never auto-drain, or the jobs are re-queued indefinitely.
- The IFC audit only reported the worker-level best-of (prev.code == CODE).

**G3. Disk-1/2 and data-4 IFC deliverables (25,751 STEPs) carry every v5 defect, including uncut openings. Never graded, no re-run decision, no owner.**
- The IFC audit recommends this in passing but filed no flaw entry for it.
- data-4 IFC: 11,099 STEPs (7.70 TB). 8,346 were read back by OCC; 2,753 of 256 MB or more were graded by markers and bbox only.
- Also in data-4: 1 `corrupt_coordinates` whole-model failure (the same pattern as the data-3 bbox_absurd models) and 1 unpublished `readback_fail` (2d0f85a3bc80).
- Tekla and SDS2 have the equivalent flaw recorded (14,772 Tekla models; 328 SDS2 jobs). IFC does not.

**G4. Code k shipped the 7.5x-8.x bolt writer (db1bolts2) to production before validation. Owner rule: "bolts only where decoded and validated".**
- Header claim: validated on 7.82/8.07/8.53. The Tekla audit measured 408 of 6,696 groups joined (357 exact, axial within 1 mm 40%) on 8.07 1908_Equipment_support, and 0 on 7.98 Parking Deck.
- 0 data-3 production results exist yet for 7.64/8.53/9.21 on k/l.
- Recommendation: gate it behind DB1_BOLTS2 or tag it approx until at least 95% of groups join.

**G5. Code l (6.1.0-rc in the DB1 STEP stage) fails 3 of 44 runs, and best-of hides it.**
- convert_error on 3585d86a380d and 48e010c8ec25 (the same KeyError), and step_kernel_crash on c114f84dc319.
- 5 DB1 rows serve a STEP older than their code label: 3585d86a380d l→h, 48e010c8ec25 l→h, 27a9febf9f71 j→h, 863be0aa5b95 i→pre-h, c114f84dc319 j→pre-h.
- History counts them as reconverted.
- Code m (local, being edited 00:58Z) contains the ambiguous-catalog guard but is not deployed.

**G6. Owner-rule conflict: class-1 IFC models contain open source shells and triangulated fallbacks.**
- `open_in_source`: 80 class-1 models, 1,456 parts.
  - ifc2step6:2195 writes "a solid source whose shell is open … offered to the reader as a closed shell (the verifier decides)". OCC healing then decides validity, and that healing is non-deterministic (step-verify-big README: 6,087 / 6,089 / 6,090 solids on 3 reads).
  - Owner decision 00:10Z: "Open source meshes: NO gap filling … tagged surfaces, class 2". These parts are counted exact.
- `L1-triangulated`: 75 class-1 models, 237 parts. The owner rules list "healed triangulated fallbacks" as approx and never class 1, yet rules.json has L1 in v6_info_tags.
- `approx-curved`: 167 models (82,025 parts). `L2-alt-source`: 104 models (6,314 parts; lead approval, not the owner's).
- The IFC audit raised only the 111 curved v5 models.

**G7. Grader arithmetic bugs not reported by any audit.**
- **Negative invalid_solids** on 3 SDS2 reference jobs: 6c5b2ed8934543db87fd2456 (-573), 7d52ec79efc6124b89d2058f (-573), a50b49804f2ff0ee7d68f673 (-80,373; 1.74 GB STEP). They are tagged `invalid_solids:-573` and graded class 2.
- **DB1 coverage_all > 1** in 59 of 106 models (max 1.1224 on 9f619582d242). classify_db1 divides `sum(written.values())`, which includes keys outside member/connection/other, by the expected member+connection+other count. Extra written items can mask missing ones.

**G8. SDS2 class 1 is never gated on the independent truth that already exists.**
- sds2-recall-nc1 has NC1 hole recall: v4c 0.536 on 59 jobs, v5.1 0.879, v5.3 0.813.
- It also has IFC product recall: v4c 0.629, v5.1 0.729. So 27-37% of SDS/2's own IFC products are not matched to a STEP piece.
- None of this feeds build_index. The SDS2 audit did not use it. Data-3 also holds 3,821 SDS/2-authored IFC exports and 610,289 unique NC1 files that could serve as truth.

**G9. A class 3 assigned from the render alone.**
- fd5ede18ecc0 (SDS2 7.425, v4): 9 parts and 9 solids, a 349,698 B STEP, class 3 `blank_render`. A render of tiny or far-off parts is not proof of a broken STEP.

**G10. New fix-plan category without proof: `source_data_absent | reference open meshes` (68 models).**
- 3,179,663 placements are skipped as `reference_part_no_closed_brep`.
- The faces exist in the job: the SDS2 audit showed that jfkf's 624 skipped placements parse and sew but fail BRepCheck. This is a converter choice, not absent source data.

**G11. Exclusion by file name only also applies in data-4: 836 xslib.db1 files.**
- The Tekla audit flagged only data-3's 96 (4 of 5-6 MB).
- Disk-1/2 showed that xslib-named "conflicted copies" can be real models.

**G12. Throughput and ETA risk for IFC s6.1.**
- 46 reconverted from 00:23 to 00:57Z, about 80/h, against 2,109 targeted: roughly 26 h.
- Adding the 1,226 class-1 models with openings adds about 15 h at that rate.
- With SDS2 first-time conversion at 10-23 h, IFC s6.1, not SDS2, may be the long pole. Nobody reports an IFC ETA.

**G13. Scope questions for the owner. No pipeline exists for these; not defects, but "every file type" needs a decision.**
- data-3 3D types without a converter: RVT 130 unique (56 new), NWC 127 (61 new), NWD 39 (30 new), IGES 473 new unique, SAT 1,506.
- Native STEP: 2,500 unique, 93 new, indexed but not read-back-validated.
- Zenitude-data-2's IFC4→STEP output (1,927) is outside all 3 audits.
- SDS2 "distinct" (4,571, by folder fingerprint) vs extraction "2,157 unique" (2,119 distinct jsetup files; 645 jsetup groups hold 3,059 rows). The numbers reported to the owner disagree. Scheduling one job per jsetup group first would reach every job and version sooner.

---------------------------------------------------------------------------------------------------------------------------------

## 3. Audit statements that are wrong, overstated or stale

- **SDS2 "main-member holes missing in every version" (968 models): overstated.** See check 14. The real gap is version- and label-specific. The 968 count is still a valid exposure count, but the "every version" wording would misdirect the fix.
- **Tekla "db1bolts2 not deployed; deploy only after ≥95%": stale.** It was deployed in code k at 00:20Z (G4). The recommended "deploy the guard as code k" is now code m+.
- **Tekla: 2ffffe4d1d78 "still class 3 waiting for j": stale.** It is now class 2 on j, with cuts_not_applied 5,142. DB1 is now 0 / 99 / 7, and 7.01 has 34 class 2 / 2 class 3 (not 32 / 4).
- **IFC "final/hold present; final jobs 0": stale.** auto_final has been on since 00:45Z (G1).
- **IFC class counts:** class 3 is now 12, not 26 (the s6/s6.1 re-runs lifted the Baylor Hurd models). d713eae4bf9dd247 (reused, 3.0e9 mm, name join, coverage 0.44) is still class 3.
- **IFC 6.1 code labelling: partly fixed after the audit.** Workers started after 00:23Z label `+s6.1` and write `.v61.step` keys (4bbcc615 is now class 2 on `+s6.1+x1`). The remaining problem is the 25 live '+s6' claims (check 12).
- **"fixed_deployed" items that are not proven in production:**
  - IFC ifcXML: 0 production conversions in data-3 and 0 re-runs of data-4's 8 failures.
  - IFC non-positive-volume / invalid / surface fixes: they do not reach the 90 rows lost to best-of (G2) or the 48 v5 fallbacks.
  - SDS2 converter duplicates and joist boxes "fixed": v5.1/v5 workers still claim first-time jobs (148 + 3 fresh), so pre-fix output is still being produced.
  - Tekla 9.50: approved in kit j with 0 conversions anywhere.
- **"source_limit_proven" labels that rest on the converter's own output:**
  - SDS2 incomplete copies (84): fine for the 64 with a complete sibling. The ones produced by the split-folder scan bug (15 → 29) are a scan defect, yet still sit under `source_file_missing | SDS/2 job files` (18 in the fix plan).
  - fix_plan `source_damaged | corrupt coordinates` (3) includes the 2 Tekla-2022 IFC models where only 2 of about 100k-157k points are bad.
  - fix_plan `source_damaged | damaged source file` (4) includes 7c68f0c9874e, which is a converter KeyError.

---------------------------------------------------------------------------------------------------------------------------------

## 4. Coverage map: conv_status top_reasons and fix plan vs the audits

- **Covered by an audit:**
  - every IFC and DB1 top_reason;
  - every SDS2 top_reason (but entry counts are not model counts, and v4/v5 synonyms split the totals: member_as_envelope 514 vs member_envelope 339, concrete_as_prism 436 vs concrete_prism 293, nominal_bolt_from_hole_stack 653 vs nominal_bolt 297, joist_as_envelope_box 317 vs joist_envelope_box);
  - fix-plan items for IFC, Tekla holes/bolts/washers/profiles/cuts, and SDS2 pieces, approx, joists, concrete, bolts, mating holes, OOM and valueerror.
- **Not covered by any audit:**
  - `source_data_absent | reference open meshes` 68 (G10);
  - `converter_feature | blank render` 1 (G9);
  - `converter_feature | grading data` 27 (DB1 Windows-manifest inventories plus 148a5d4883db `step_vs_decoder_join_unavailable`, a DB1 STEP over 1 GB);
  - `converter_feature | sds2 stage 2 failure` 18, which promises lift 18 → class 1 for stage-1 members-only output (the SDS2 audit mentions 10 st2 cases only);
  - DB1 `not_read_back_out_of_memory` (7.30 top_reason, 7c82c44be6c7).

## 5. Versions present in the data but absent from every matrix

- **IFC Disk-1/2 (14,652) and data-4 (11,099) by schema, container and authoring tool:** no matrix at all. data-4 has 1,663 ifcZIP and 5 ifcXML, plus 6 IFC2X2_FINAL relabelled.
- **data-4 SDS2 (173, incl. 6.336) and Disk-2 run-2 (909):** only mentioned. No per-version classes.
- **data-3 `.xml` (5,220 unique) and `.ifc_120321` (1):** not content-checked, so it is unknown whether any ifcXML exists.
- **conv_status itself:** versions.ifc still shows IFC2X2_FINAL 1 (true 6) and 'unknown' 47. versions.db1 shows data-3 only. versions.sds2 shows bands only. converters.ifc is hard-coded 'ifc2step5' (build_index.py:1525).

---------------------------------------------------------------------------------------------------------------------------------

## 6. Top actions, in priority order

1. Before anything else, set `auto_final` false or add a hold, until:
   - the class-1 openings re-run, the SDS2 class-2 un-pause and the v4 re-run are done;
   - step_verify_big is wired into the final read-back;
   - SDS2 is added to final_jobs (G1).
2. Add an IFC reconvert rule for class 1 with openings on transcoded bodies, on `+s6.1`. Meanwhile tag those models `openings_not_applied`: 1,226 exposed, 1,039 proven (checks 1-2).
3. Fix the grader best-of in build_index `once()` for all pipelines. Rank by coverage, then exact-part count, then class, and prefer the newer converter. This frees 90 IFC rows (7 with s6.1) and 12 DB1 rows (G2, check 7).
4. Deploy the db1bolts ambiguous-entry guard (code m). Then re-run 7c68f0c9874e, 3585d86a380d and 48e010c8ec25, and make worker best-of fallbacks visible as regressions (G5).
5. Gate db1bolts2 output, or tag it approx, until at least 95% of groups join to the Tekla IFC on 7.64, 8.07 and 8.53 (G4).
6. Decide the Disk-1/2 and data-4 IFC re-run (25,751 STEPs) and assign an owner (G3).
7. Get an owner ruling on `open_in_source` and `L1-triangulated` in class 1 (80 + 75 models) (G6).
8. Retire old-generation workers: SDS2 v5.1/v5.2/v5.3/v5 claims (236 fresh) and IFC '+s6' (25 fresh). Also re-point the 3 out-of-memory class-3 jobs to their published v5.1 STEPs (checks 10-12).
9. Wire the NC1 and IFC recall checks into the SDS2 class-1 gate, and correct the SDS2 "every version" holes statement (G8, check 14).
10. Fix the grader arithmetic: negative invalid_solids, DB1 coverage_all > 1, blank_render as the sole reason for class 3 (G7, G9).
