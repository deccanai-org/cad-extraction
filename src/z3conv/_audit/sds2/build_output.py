#!/usr/bin/env python3
"""Assemble the structured SDS2 audit (versions + flaws + summary) from the BOX-C outputs in this folder."""
import json

ex = json.load(open('boxout2/versions_exact_entries.json'))
bd = json.load(open('boxout2/versions_band_entries.json'))

special = [
    dict(version="2015.25 / 2015.33 job folders (SDS/2 2015 = jsetup 7.425 / 7.433)", status="partial", distinct=318, class1=6, class2=133, class3=52,
         notes="7.425 267, 7.433 42, 7.331 3, 7.412 2, 7.404 1, other 3; 127 ungraded (45 claimed, 66 with memory-kill deferrals); corpus B 97 / R 25 / C 13 / A 4; "
               "class-3: no_member_records_read 18 (base-v5 calibration failures, 2015.25 DWF jobs), source_no_members 16 (proven empty), converter_wrote_nothing 10 "
               "(STEP write failed: unlinked DWF variant pp3/njk/duct-l5 and others), converter_out_of_memory 2 (fleet), member_coverage 3; dominant class-2: nominal bolts 73, "
               "member envelopes 63, approx profiles 57, concrete prisms 55 (v4 tags). Snapshot 00:22Z."),
    dict(version="training sandboxes (2015.25 jobs.7z + SDS_Jobs_7.331 jobs.7z)", status="failing", distinct=179, class1=0, class2=70, class3=74,
         notes="35 ungraded; class-3 reasons: source_no_members 28 (empty_job_proof), no_member_records_read 22, converter_wrote_nothing 18, converter_out_of_memory 2, "
               "member_coverage 2, valueerror 1, blank_render 1; corpus R 56 / C 11 / B 3. Most are DWF/ReferenceModel imports: v5.1 writes stored B-reps but skips most "
               "placements (see reference flaw)."),
    dict(version="reference-model jobs (DWF / IFC / ReferenceModel import members)", status="partial", distinct=106, class1=0, class2=65, class3=41,
         notes="68 jobs with written reference parts (65 class 2 R, 3 class 3 by member_coverage; 64 still v5.1, 2 v5.2, 1 v5.3, 1 v5.4): 334,069 parts written "
               "(8,255 open shells in 3 jobs), 3,179,663 placements skipped (reference_part_no_closed_brep, 69,756 by the 5,400 s time budget); 23 'converter_wrote_nothing' "
               "(STEP write failed; pp3 345,231 and njk 45,189 unlinked frames proven by the manifest but graded unproven); 15 single-member DWF/ReferenceModel jobs fail "
               "'too few members to calibrate (0)' on v5.1-v5.4 (7.425/7.433/7.613/7.619/7.720); 1 'REFERENCE MODEL' member not recognised (7.720). Counts are lower bounds "
               "(pending jobs not included)."),
    dict(version="empty / seed jobs", status="failing", distinct=41, class1=0, class2=0, class3=41,
         notes="41 class-3 'source_no_members (empty job, proven)' with empty_job_proof (member files 0, zero mem_idx): 7.425 21, 7.331 13, 8.007 2, 7.328 2, 7.412 1, unknown 1, "
               "+1; seed jobs with members but no geometry (DWS_SEED_JOB_STRUMIS type) get manifest class 3 C (grader gives 2 C for 3 of 4). No STEP by nature: correctly classified as proven source limits."),
]

F = []
def add(flaw, status, evidence, owner, action, models, versions):
    F.append(dict(flaw=flaw, status=status, evidence=evidence, owner=owner, recommended_action=action, models_affected=models, versions=versions))

add("Double bolts: nominal hole-stack bolts are written on top of SDS/2's own stored bolt hardware (BLT head/nut/washer pieces written as exact B-rep)",
    "UNOWNED_GAP",
    "BOX-C probe with deployed v5.3 on Befor North 2259-OKANA RD E1&E2_JOB (11be36488546683dedb49806, 8.007): all 276 nominal bolts lie on the axis of stored BLT pieces "
    "(828 of 1,104 BLT pieces, 3 per bolt; SDS2 bolt records 17) - _state/agentwork/audit-sds2-pipeline/diag/d2_bolts_befor_north/bolt_probe.json. to_step2 marks a hole "
    "stack 'covered' only by SDS2 bolt records, never by BLT pieces; unchanged in deployed v5.4.1 (to_step2.py 1406-1413) and the v5.5 draft. Exposure: 70 v5.x jobs with BLT pieces (67,436) and "
    "nominal bolts (434,046); 548 v4 STEPs with fastener pieces (911,398) and nominal bolts (1.70 M). The duplicated stacks are also graded as nominal_bolt stand-ins.",
    "SDS2 fixer", "Treat stored BLT/nut/washer pieces coaxial with a hole stack as covering it (no nominal bolt); count those stacks as exact bolts; re-run the 70 v5.x + 548 v4 jobs.",
    618, "7.2xx-8.0xx (v5.x: 7.3 36, 7.6 11, 7.7 8, 7.4 6, 8.0 5, 7.2 4)")

add("Reference/import member types not recognised by the v5.x reader (deployed v5.4.1 too): calibrate()/sparse_layout() marker regexes lack 'DWF Import'/'ReferenceModel', and REFERENCE_TYPES lacks 'REFERENCE MODEL'",
    "UNOWNED_GAP",
    "14 non-empty jobs fail 'ValueError: mem_idx: too few members to calibrate' on v5.1-v5.4 (+1 v4): 7.613 dfgter 1c5919db / hhju bbe1a0f2 / HBA df94ee51 (~20.7k files each), "
    "dd 2e825feb; 7.619 tg 414b6e93, fgfg a83895c3, sd2134 ae39df51 (39,929 files), SWE b0a4d399, DE b0fb2105; 7.720 DFGH 606dfec9, JKJJK 4a88c3fd; 7.425 STR 2ac238d7, "
    "CCCVD db4c7964; 7.433 nxc 50e40530. BOX-C census (v5.3 reader): DFGH/tg/dfgter/STR each have 1 member file typed 'DWF Import'/'ReferenceModel', 0 calibration markers, "
    "sparse_try None, 442 / 1,647 / 20,750 / 1 piece files. IFC_RH Palo_Grand Stair (ade4790f, 7.720): member type 'REFERENCE MODEL' with 1,888 frames, only 44+45 placements "
    "written of 1,159 piece files -> class 3 member_coverage 0.01. v5.4.1 sds2job.py lines 187/311/330 unchanged; 27 more base-v5 results fail the same way and are queued.",
    "SDS2 fixer", "Add the import types to both marker regexes (accept a single reference member) and match REFERENCE TYPES case/space-insensitively; bump the class-3 re-run rule code so these 15 (+27) jobs actually re-run.",
    16, "7.425, 7.433, 7.613, 7.619, 7.720")

add("Reference-model placements dropped at scale: sewn open shells that fail BRepCheck are skipped under the misleading reason 'reference_part_no_closed_brep'; time budget drops more; 64 of 68 reference jobs still on v5.1 (no open-shell path)",
    "in_progress_owned",
    "00:22Z: 68 reference jobs wrote 334,069 parts (8,255 open shells in 3 jobs) and skipped 3,179,663 placements (reference_part_no_closed_brep; 69,756 by SDS2_REF_BUDGET_S 5,400 s). "
    "BOX-C cause analysis of jfkf (23c1072354fa68f340d83fcc, 7.331, v5.3): all 624 skipped placements = 47 pieces x 108 faces that parse and sew but fail BRepCheck "
    "('open_shell_brepcheck_invalid') - diag/d1_ref_jfkf/ref_causes.json. b63fa66d / df6dfb4d (7.331, v5.1): ~70k placements each unwritten -> class 3. Class-2 re-runs of the "
    "v5.1 reference jobs are paused. The _pfix sds2-pieces-not-built stream (classify_ref / diag_ref, v5.5 draft) is on it; its draft source_gap() files double-sided open meshes "
    "as 'source_mesh_open' (source data absent) although their faces exist and the v5.2 path can write them as tagged open surfaces.",
    "_pfix sds2-pieces-not-built stream + SDS2 fixer (converter); lead/builder (re-run)", "Write BRepCheck-invalid sewn shells as tagged face sets (or ShapeFix_Shell first); split the skip reason (parse / face limit / invalid shell / absurd / placement); raise or parallelise the reference budget; re-run all 68 jobs.",
    68, "7.3xx (36: mostly 7.331/7.328), 7.4xx (32: 7.425/7.433)")

add("Class-1 SDS2 set is not trustworthy: all 41 v4 class-1 STEPs are graded from the converter's own inventory without a manifest, never re-run (v5.3 rule include_reused=false), and the v4-inventory and manifest grading paths disagree",
    "UNOWNED_GAP",
    "41 of 43 class-1 SDS2 models are reused v4 STEPs (40 disk-2-run-2, 1 data-4); their grade reuses run-2 verify output (validate.by 'converter verify ... of the reused run'). "
    "BOX-C re-run of all 41 with v5.3 (deployed until 00:10Z): manifest 40 class 1 / 1 class 2 (fba8adaf BACK UP MILL_OFFICE 7.613: v4 silently omitted 18 joists); v4 STEPs held converter "
    "duplicates in 3 (d6dfde1c 6, dfbfc59b 4, fba8adaf 1); an emulation of the coordinator rules (coverage, stand-ins, 5 % ratio / family) on those manifests gives 25 / 13 / 3. With deployed v5.4: manifest 33 class 1 / 8 class 2 "
    "(7 jobs with 905 mating_holes_not_stored, e.g. 81a661e3 225, fba8adaf 552, 68f7d010 12) and the same emulation 22 / 16 / 3 - diag/d5_summary.json, diag54/.",
    "builder (grader, reconvert rules) + lead", "Re-run every v4 class-1 job on v5.4 and grade class 1 only from a manifest; reconcile the two grading paths before the final pass.",
    41, "7.115, 7.135, 7.200, 7.245, 7.309, 7.312, 7.328, 7.331, 7.425, 7.613, 8.004, 8.007")

add("Main-member bolt holes are missing in every SDS2 version; only v5.4 (first-time jobs) tags them and recovers few",
    "in_progress_owned",
    "v5.3 Known limits; Greenwood GMS (7.312) NC1: 392 holes on 26 matched parts, 4 decoded; v5.4f: 12 holes derived, 689 mating_holes_not_stored, NC1 4/392 matched; v5.4 CHANGES: "
    "Greenwood 0/90 matched. v5.4 / v5.4.1 deployed 00:10Z / 00:27Z for first-time jobs only (no re-runs): index 00:49Z - 81 of 105 v5.4.x class-1/2 results tag mating_holes_not_stored (197,564 holes) and 93 cut holes_derived_from_bolts (87,213); v4/v5.0-5.3 STEPs (968 graded jobs with decoded connection-"
    "plate holes) carry the gap silently; 7 of the 41 class-1 jobs show 905 missing mating holes on v5.4. Derivation needs SDS2 bolt records, which cover only 55-75 % of bolts "
    "in every version (nominal share 25-45 %; GMS 4 of 398).",
    "SDS2 fixer", "Validate v5.4 against NC1 on more jobs; decode the remaining bolt records; re-run all graded SDS2 jobs on v5.4 so the gap is at least tagged.",
    968, "all (7.0xx-8.0xx)")

add("False 'converter_out_of_memory' class 3: fleet declares out_of_memory after 5 watchdog kills regardless of the job's RSS, and the verdict overwrites earlier good results",
    "UNOWNED_GAP",
    "11 jobs failed out_of_memory (recorded peak RSS 0.46-6.02 GB for 7, 33.7 GB for 1, none for 3) with retry reservation 22-62 GB on 495 GB hosts (CLAYTON_JOB 7805e621 / 33a75ed6 0.53 GB, PERCEPTIVE "
    "a2243fb1 0.46 GB, MELBOURNE ff442ef1 2.02 GB). convfleet._finish (kills >= 5) bypasses worker best-of: MELBOURNE (v5.1 STEP 508 MB + manifest), l-arch 556b8979 (32 MB) and "
    "P-01 bee88c67 (1.2 GB) have published v5.1 STEPs under conversions/sds2-step/<id>/v5.1/ yet are class 3. Results carry code v5.3, so the class-3 rule (code v5.2) never re-runs "
    "them; the 00:16Z and 00:44Z convfleet builds keep the same verdict rule. The 00:44Z build adds reason-based redo entries (redo_ids.json), but no SDS2 redo_ids.json exists yet.",
    "builder", "Count only kills with RSS >= expected toward the verdict; never overwrite an ok/ok_stage1 result with a fleet failure; add a redo_ids.json entry {reasons:[out_of_memory]} to re-open the 11 now (v5.4.1 uses 18-42 % less memory) and re-point the 3 to their v5.1 STEPs meanwhile.",
    11, "7.245 (4), 7.312 (4), 7.425 (2), 7.331 (1)")

add("Memory watchdog kill storms (legacy 'largest on host' rule kills sub-GB jobs) slow the SDS2 fleet",
    "in_progress_owned",
    "512 fleet logs: 428 WATCHDOG kills, 426 by the legacy 'largest on host' rule, 236 at RSS < 1 GB; 838 deferral records (831 record peak < 1 GB); OOM kills/30 min "
    "291 (23:38Z) -> 182 (00:12Z) -> 96 (00:23Z) -> 109 (00:29Z). New convfleet deployed 00:16Z (legacy-process detection, expected-memory admission, victim choice by RSS/age).",
    "builder", "Confirm kill rate and throughput after the 00:16Z deploy; record real peak RSS in deferral records; keep sub-GB jobs out of victim selection.",
    838, "all (deferrals: 7.3xx 518, 7.4xx 83, 7.2xx 64, 7.6xx 53, 7.1xx 49, 8.0xx 36, 7.7xx 32, 7.5xx 3)")

add("First-time SDS2 conversion coverage: 86 % of new jobs not yet converted",
    "in_progress_owned",
    "conv_status 00:29Z: to_convert 3,812, done 530, in flight 514, pending 3,282; graded 1,285 of 4,571 distinct (43 / 1,089 / 153). Done rose 79 (21:11Z) -> 211 (22:34Z) -> 321 "
    "(23:38Z) -> 530 (00:29Z), ~135/h -> ~25 h left at that rate. 7.0xx has no v5.x result (41 of 47 pending), 7.1xx 710 of 870 pending, 8.0xx 106 of 168.",
    "builder", "Keep the fleet on first-time jobs; report per-version ETA; prioritise versions with no v5.x evidence (7.0xx, 7.1xx, 7.5xx, 8.0xx).",
    3796, "all")

add("Improved converters are not applied to existing class-2 results: class-2 re-runs paused 23:52Z and v5.4 deployed with 'no class-2 re-runs'",
    "in_progress_owned",
    "coord/reconvert.json: sds2_paused (v5.2 joist/weight/family/invalid/pieces rules, v5.3 converter-duplicate rule), _note 'paused 23:52Z until first-time conversions finish (lead)'; "
    "only the class-3 rule (code v5.2) is active. History: v5.2 rule 60 of 818 reconverted, v5.3 rule 0 of 73. 00:22Z: 1,120 of 1,209 graded class-2/3 models not targeted; data-3 "
    "class-2 results by converter: v5.1 188, v5.3 94, v5.2 25, v4 17, v5.4 14, v5 3.",
    "lead / builder", "Resume class-2 re-runs on v5.4 after the first pass; bump rule codes per fix so v5.3/v5.4 results are retried when a fix lands.",
    1120, "all")

add("v4 STEPs (759 reused + 17 data-3) are outside every re-run rule and contain untagged stand-ins, joist solid blocks, approximate pieces without holes and possible converter duplicates",
    "UNOWNED_GAP",
    "Paused rules match only weight/invalid/pieces_not_built/stage-1/load-error tags and 7.6 joists: 526 v4 class-2 STEPs match nothing even after un-pausing; the 41 v4 class-1 are "
    "excluded. BOX-C scan of 6 v4 STEPs (one per stand-in type): 0 '[approx' product names - joist boxes named 'JOIST #5 / 26K9 (member envelope)', 9 approximate profiles unnamed, "
    "'#1 / Conc. 66.5 yards (piece 2, inst 1)', '(nominal heavy hex)' bolts (diag/d3_v4_tags.json). Index: v4 joist boxes in 318 models, approximate pieces without holes in 453, "
    "nominal bolts in 650; 119,693 same-piece/same-origin rows across members in 599 of 759 v4 pieces CSVs (upper bound incl. SDS2 twins).",
    "builder (reconvert rules)", "Add a rule that re-runs every converter=v4 result (all classes, include_reused) on v5.4; until then, do not ship v4 SDS2 STEPs as tagged deliverables.",
    776, "all (7.3xx 468, 7.1xx 114, 7.4xx 106, 7.2xx 38, 8.0xx 16, 7.6xx 12, 7.5xx 10, 7.0xx 6, 7.7xx 5, 6.3xx 1)")

add("Superseded converter generations keep converting first-time jobs; their class-2 results will never be re-run",
    "UNOWNED_GAP",
    "Live claims (fresh < 25 min, ~00:35Z): v4 11, v5 3, v5.1 182, v5.2 23 vs v5.3 144, v5.4 176 (stale: v5.1 106, v4 6, v5 2). Data-3 first-time graded results by label: v5.1 227, "
    "v5.3 126, v4 47, v5.2 34, v5 30, v5.4 29.",
    "builder (fleet hot-reload)", "Put old-generation processes in finish-only mode (no new claims) or add a rule re-running any result whose label is below the current converter.",
    219, "all")

add("Grader: member coverage counts material-less member records (empty MISC members) as missing -> false class 3/2; v4 and v5 paths disagree on the same content",
    "grader_issue",
    "b244541c NORTH URBAN REVIT (7.331, v5.1): 1,264/1,264 placed pieces exact, steel 1.026, manifest class 1 A -> index class 3 member_coverage 0.12; BOX-C probe: all 4,734 'without "
    "geometry' members are MISC (no section) with header frames only and no material blocks (diag/misc/b244541c...json); its v4 twin ca8aba5e is class 1. Also ade4790f (0.01), "
    "c48a9d62 (0.10, v4 twin e5da7656 class 2), b63fa66d / df6dfb4d (0.33). Re-run of the 41 v4 class-1 jobs: 12 drop for coverage < 1 (3 below 0.5). 26 manifest/grader class "
    "disagreements at 00:22Z (manifest 'broken' -> 2 B for 6, 3 C -> 2 C for 3, ...).",
    "builder", "Use members with a section or material blocks as the denominator; report material-less members as info; align manifest.classify and coordinator rules.",
    17, "7.312, 7.331, 7.425, 7.720, 8.007")

add("Grader: coverage formula ignores reference parts and converter-duplicate removal (reference jobs can never be class 1; removing a duplicate demotes a job)",
    "grader_issue",
    "coverage_connections = pieces_written / placed_pieces: 5 reference jobs whose manifest is class 1 R (all parts closed, none skipped: 0965ed04 1,310, 53b56d6f 422, 0e6cc241 14, "
    "7d68ecfb 14, e395aceb 2) get coverage 0.0 -> class 2 R; GOPAL_TRAINING_FAB d6573095 (7.312, v5.4): placed 48, written 47, 1 converter duplicate skipped, no stand-ins -> "
    "class 2 B (manifest 1 A).",
    "builder", "coverage = (pieces_written + reference_parts) / (placed_pieces - converter_duplicates_skipped).",
    6, "7.312, 7.328, 7.331, 7.425")

add("Grader: proofs inside failed results are ignored (unlinked-reference proof graded 'source NOT proven empty')",
    "grader_issue",
    "pp3 df70ab50 (7.425, v5.3) and njk bbc38a2b (7.425, v5.2) results carry manifest class 3 R with reference_unlinked_frames 345,231 / 45,189, but classify_sds2 only reads "
    "empty_job_proof, so the index says 'converter_wrote_nothing (source NOT proven empty ... re-run on v5.1)'. BOX-C check: no f_guid_map and no text GUIDs in main/ or mem/ of "
    "pp3 / njk / duct-l5 (consistent with the fixer's proof).",
    "builder", "Map manifest class 3 R with reference_unlinked_frames > 0 to a proven source reason; keep duct-l5 (v5.1) in the queue.",
    3, "7.425")

add("Status/fix-plan reporting ranks SDS2 flaws by stand-in entries, not models; numeric tags fragmented",
    "grader_issue",
    "conv_status 00:29Z SDS2 top_reasons: '2:concrete_prism' 3,941 (157 models), '2:joist_as_envelope_box' 2,833 (318 models), '2:member_envelope' 1,605 (184); the real top "
    "model counts are nominal_bolt_from_hole_stack 650, member_as_envelope 511, profile_fallback_approximate_no_holes 453, concrete_as_prism 433. versions[].top_reason uses the "
    "same entry counts; 'steel_weight_ratio_<value>_outside_5pct' is not normalised (40+ keys).",
    "builder", "Count distinct models per type; normalise numeric tags in versions_matrix and top_reasons.",
    1089, "all")

add("Fix plan labels converter gaps as source_data_absent without proof (bolt records, undetailed members, concrete shapes, 7.7+ joists)",
    "source_limit_unproven",
    "'bolt records absent' 773 models: decoded SDS2 bolt share is 55-75 % in every version (7.135 0.61-0.70, 7.312 0.65-0.67, 7.425 0.63-0.65, 8.004 0.55-0.62) and Befor North's "
    "nominal bolts sit on stored BLT hardware; 'undetailed members' 669: 12 of 14 members-only jobs hold 37-8,684 piece files (6591ab64 8.004: 1 envelope, 8,684); 'concrete "
    "shapes' 561: SDS2 stores concrete meshes, the converter builds prisms (concrete_local) when mesh and volume disagree; 'joist vendor design' 437 also covers 7.7xx joist pieces "
    "whose stored multi-body B-rep does not close (415 parts / 7 jobs) and JOIST members with rolled sections (L4x4x1/4) boxed (24 v5.x models).",
    "builder (explain()) + SDS2 fixer", "Re-categorise as converter_feature until a per-job proof exists (e.g. member file has no material blocks; no record of any layout).",
    773, "all")

add("Read-back repair incomplete: solids still invalid after STEP read-back on v5.1-v5.3",
    "UNOWNED_GAP",
    "6a37cad8 (7.312, v5.3) 5 invalid, ce009545 (7.312, v5.3) 3, bc902407 (7.425, v5.1) 4, cd34ed67 (7.425, v5.1) 4, 96cd8ec7 (7.425, v5.1) 1, 0774dda6 (7.312, v5.2) 1 - manifest "
    "'0 broken', index class 2; VBCVB 30e24d25 (7.433 reference) failed invalid_solids -> class 3.",
    "SDS2 fixer", "Extend pass 2/3 so no invalid solid survives (drop with exact_solid_invalid_at_placement); re-run the 7 jobs.",
    7, "7.312, 7.425, 7.433")

add("Scan splits loose-folder SDS2 jobs into main/ and mem/+subm/ contents, so each half fails 'job_folder_incomplete' (class 3 'source_job_files_missing')",
    "UNOWNED_GAP",
    "BOX-C d7: 15 loose job folders split into 29 contents, e.g. Volkswagen_JOB 8fb19183 (main, 12 files) + 033d87b3 (mem); CAPITAL ONE PLANO 23e2897b + 6d3cda08 (14,040 files); "
    "RiverPoint_Job 461efdd1 + 830f9335 (14,891); XXX_JOB_T7 069d940d + fe00aded; already class 3: 8fb19183, d7645623, fe00aded; the rest pending and will fail the same way.",
    "builder (scan)", "Group loose files by the job root (parent of main/ mem/ subm/) and merge the halves; re-scan and convert.",
    29, "7.135, 7.152, 7.258, 7.312, unknown")

add("Incomplete job copies: main/job_mtrl, mem/mem_idx or subm/subm_idx absent in the stored source",
    "source_limit_proven",
    "84 contents complete_layout=False (d7): missing jsetup+job_mtrl 16, +subm_idx 19, job_mtrl 18, mem_idx+subm_idx 25, mem_idx 3, other 3; 38 still hold member and piece files "
    "(Two25_Job 2dd5fedd: 9,725 member + 4,180 piece files, no job_mtrl; BOSK_EA_VOID_Job 9b070917: no main/, 27,669 piece files); 64 have a same-name complete copy; plus 10 stage-1 "
    "fallbacks where stage 2 hit FileNotFoundError subm/subm_idx. Extraction verified complete (final_verify 0 missing), so the files are absent from these copies.",
    "SDS2 fixer (fallback) + builder (dedupe)", "Add a reference-style fallback (place subm B-reps from mem/<n> blocks without the piece table); mark copies whose job exists complete elsewhere.",
    94, "7.1xx-8.0xx, unknown")

add("Empty / seed SDS2 jobs (no member files)",
    "source_limit_proven",
    "41 class-3 'source_no_members (empty job, proven)' with empty_job_proof (member files 0, zero-filled mem_idx) on v5.1-v5.4, e.g. jhjhj 05e3d285 (8.007), d1 080d0e04 / c123 0b4202d4 "
    "(7.425 2015.25 jobs.7z); seed jobs with one section-less member get manifest class 3 C.",
    "none needed", "Keep as class 3 with the proof; exclude from conversion-failure counts.",
    41, "7.328, 7.331, 7.412, 7.425, 8.007, unknown")

add("Open-web joists in 7.0-7.6 jobs exist only as designations (stand-ins derived from SJI tables, tagged approx)",
    "source_limit_proven",
    "Joist members carry no material blocks; v5 writes joist_openweb_standin (137 v5.x models, 'needed: vendor joist design'); v4 boxes in 318 models; 7.7+/8.0 joists stored as "
    "pieces are exact except the non-closing multi-body cases (separate flaw). Joist class is a pending owner decision (tolerated_standin_types empty).",
    "owner decision (joist class switch)", "Keep class 2 / B unless the owner tolerates joist_openweb_standin; replace v4 boxes via the v4 re-run.",
    437, "7.0xx-7.6xx")

add("Special pieces not built (no usable special geometry, failed fallbacks, >5x weight fallbacks)",
    "in_progress_owned",
    "Graded STEPs: no_usable_special_geometry 47,588 pieces in 103 jobs (7.4xx 19,079, 7.2xx 18,272, 7.3xx 6,861, 8.0xx 2,760), fallback_builder_failed 4,280 in 93, "
    "fallback_over_5x_source_weight 2,665 in 127 (v4 skips; v5 stand-ins); fix plan 'sds2 pieces not built' 304 models; now picked up by the _pfix sds2-pieces-not-built stream (groups.json, v5.5 source_* reasons + grader diff).",
    "_pfix sds2-pieces-not-built stream", "Decode special geometry (studs, rods, rebar, hooks) from the stored meshes; tag rather than skip.",
    304, "all")

add("'absurd_extent_corrupt_source_geometry' drops pieces as corrupt without proof",
    "in_progress_owned",
    "4,208 pieces in 27 jobs (8.0xx 2,834, 7.3xx 1,334, 7.7xx 32): DMV_BOSK_EA_JOB 1f3ff36a (8.004) 296 pieces on MISC member 444 named '#7E8' / '#5E-8' (rebar-like marks); 0774dda6 "
    "(7.312, v5.2) 498 of 9,875 placed steel pieces (> 5 %, manifest 'broken', index class 2); 1 job failed absurd_bbox on v5.3. Under investigation in _pfix sds2-pieces-not-built (groups.json: 4,104 placements / 87 pieces / 25 models).",
    "_pfix sds2-pieces-not-built stream", "Inspect the records (likely curved/bent special geometry) before calling them corrupt; record proof per piece.",
    27, "7.3xx, 7.7xx, 8.0xx")

add("SDS2-decoded bolts drawn as A325/A490 heavy hex whatever the decoded type, no washers, and counted exact",
    "UNOWNED_GAP",
    "to_step2.bolt_local: HEX_H heavy-hex table 0.5-1.5 in (other diameters 0.625d head / d nut), the jsetup bolt type (e.g. A325N) only in the label, washers never drawn; 7.0xx / early "
    "7.1xx f32 records have no type byte (bolts.py). Owner policy bolt_standard_geometry_exact counts table geometry exact only for a decoded standard. 902 graded jobs hold 6.6 M "
    "SDS2 bolts; 11 of the 41 class-1 jobs hold 1,535.",
    "SDS2 fixer + builder (grader)", "Key head/nut/washer geometry on the decoded type; tag bolts with unknown type or off-table diameter as approx.",
    902, "all")

add("Nominal (guessed) bolts are written although the owner rule says bolts only where decoded and validated",
    "UNOWNED_GAP",
    "v4 'nominal_bolt_from_hole_stack' in 650 models (1.74 M bolts, untagged in v4 STEPs), v5 'nominal_bolt' in 152 models (tagged approx); stage-2 nominal bolts 7.3xx 2.17 M; "
    "at least some sit on stored BLT hardware (double-bolt flaw).",
    "lead / owner decision", "Decide: omit nominal bolts, or keep them tagged and class 2 only; apply via re-run.",
    802, "all")

add("Approximate pieces where SDS/2's stored B-rep does not sew (profile extrusions, plate outlines, mesh cylinders, piece-table boxes, grating panels)",
    "in_progress_owned",
    "Index 00:49Z v5.x class-1/2: rolled_profile_extrusion 22,643 parts in 312 jobs, plate_from_vertices 13,943 in 214, mesh_cylinder 89,072 in 165, piece_table_standin 662 in 58, "
    "grating panels 8 (+117 v4 models); v4 approx profiles/plates without holes in 453/321 models; fix plan 'sds2 approx pieces 7.x': 7.3 390, 7.1 93, 7.4 86, 7.2 35, 7.6 29, 7.7 23, "
    "8.0 14, 7.5 9, 7.0 5, 6.3 1 models. Streams: _pfix sds2-approx-pieces-7x (cand_brep / draft_brep) and sds2-grating-cylinders (grating.py).",
    "_pfix sds2-approx-pieces-7x and sds2-grating-cylinders streams", "Recover exact B-reps (repair sewing) before falling back; keep the [approx] tags; re-run the affected jobs.",
    685, "all")

add("Best-of keeps an older STEP over a newer one on a <=0.1 % weight-ratio tie-break",
    "grader_issue",
    "2263534c (7.331): v4 kept over v5.1 (|ratio-1| 0.0 vs 0.0004); 693974d8 (7.613): v4 over v5.1 (0.0110 vs 0.0112); e730aa98 (7.425): v5.2 over v5.3 (0.0177 vs 0.0178). "
    "The kept v4 STEPs lack [approx] tags and v5 joist/hole fixes.",
    "builder (worker.process)", "Prefer the newer converter when class, invalid and skipped tie and |delta ratio| < 1 %.",
    3, "7.331, 7.425, 7.613")

add("Family-weight 5 % rule demotes jobs whose pieces are all exact SDS2 B-rep (faceted rounds / bars)",
    "in_progress_owned",
    "146 graded models flagged family_weight_outside_5pct (RB 29, WS 15, W 11, CV 9, CK 8, ...); in the 41-job re-run, 4 all-exact jobs fail it (5330663e L, 81a661e3 FL, af2ab64e L, "
    "dfbfc59b W/ROUND); ROUND 0.930 on Binney is SDS2's own faceted pipe (REGRESSION.md). _pfix sds2-weights-failures selected 96 'fam' + 50 'w5' jobs.",
    "_pfix sds2-weights-failures stream + builder (grader)", "Calibrate tolerances per family (faceted round families) or only apply to approximate pieces.",
    146, "all")

add("Crash bugs: CSU_JOB still raises in deployed v5.4.1; KJL fixed in v5.4.1 but not yet re-run",
    "in_progress_owned",
    "CSU_JOB 347cb74f (7.312): 'ValueError: mem_idx: member work points not found' (still raised at v5.4.1 sds2job.py:218); KJL f3e696bf (7.425): 'zero-size array to reduction operation "
    "minimum' (preview; v5.4.1 CHANGES: preview skipped cleanly when nothing is drawable) - both class 3 'valueerror', in the redo queue and in the _pfix sds2-weights-failures 've' selection (15 jobs).",
    "SDS2 fixer + _pfix sds2-weights-failures stream", "Fix the work-point path before the queued re-run; confirm KJL on v5.4.1.",
    2, "7.312, 7.425")

add("Class-3 re-run rule is keyed to code v5.2, so class-3 results produced by v5.3/v5.4 are never retried after a fix",
    "UNOWNED_GAP",
    "code_ge(result code, rule code) treats v5.2/v5.3/v5.4 results as satisfied: affects the 11 false OOM verdicts (code v5.3), 5 v5.3 + 1 v5.4 calibration failures, step_write_failed on v5.2-v5.4 (7, incl. pp3 / njk), job_folder_incomplete on v5.3/v5.4 (9) and any later fix.",
    "builder (coord/reconvert.json)", "Use a new rule code per fix (e.g. z3-sds2-v5.5-...) targeting the affected reasons.",
    20, "all (>= 20 class-3 results)")

add("Built-up PLG/WPS/WBX abort fixed in code but not yet demonstrated on data-3",
    "in_progress_owned",
    "13 class-3 v4 results 'ValueError: PLG...: built-up dimensions match neither name nor weight' (BG PODIUM_Job x12, Boston_Garden_Checkers, 7.331) are in the redo queue; v5+ "
    "_builtup() never raises (REGRESSION.md: BG PODIUM x3 + Checkers -> 0 aborts locally); live v5.x manifests hold only 2 PLG pieces (1 job); ~100 Boston Garden copies pending.",
    "builder (re-run) / SDS2 fixer", "Confirm on the first BG PODIUM re-run; check built-up weight tags.",
    13, "7.331")

add("Unknown / newer SDS2 job formats (unreadable or missing jsetup)",
    "UNOWNED_GAP",
    "2 'unreadable': 16-18_ARUNDEL_ES_JOB 54a18fb6 (binary jsetup header, all canonical files, 11,104 files) and A3-HIMD_JOB c932d705 (jsetup is a boost-XML archive with IFC fields; no "
    "job_mtrl / mem_idx - possibly SDS2 2021+); 39 'unknown' (no main/jsetup: split or incomplete folders). Not yet run.",
    "SDS2 fixer", "Identify the format of the two unreadable jobs before they are run; route 'unknown' via the split-folder fix.",
    41, "unknown, unreadable")

add("6.3xx jobs have no decoded face topology: every piece approximate",
    "source_limit_unproven",
    "data-3 6.322 (1 reused v4 job: 104 profile + 27 plate fallbacks without holes, 1 grating panel, class 2); data-4 4 jobs (CHOWNS 6.336, defaultAdapt). The fixer states '6.3xx "
    "jobs have no readable face topology' without a layout proof.",
    "SDS2 fixer", "Probe the 6.3 piece-file layout before calling it a source limit.",
    1, "6.322")

add("Data-4 and Disk-2 run-2 SDS2 outputs remain v4-final",
    "UNOWNED_GAP",
    "zentitude-data-4 conv_status (final 2026-09-30, code z4-sds2-v4): 173 jobs, 133 ok / 40 failed (13 invalid_solids, 8 no_members_to_calibrate, 6 job_folder_incomplete, 6 "
    "missing_job_file, 4 qa_fail, 2 other, 1 step_write_failed); Disk-2 run 2: 754 accepted / 155 not accepted (CONTEXT.md). Only the 759 contents shared with data-3 are re-graded.",
    "lead", "Decide whether data-4 / Disk-2 SDS2 get the v5.4 re-run.",
    328, "6.3xx-8.0xx")

add("Welds are never modelled",
    "source_limit_unproven",
    "issues_info on every SDS2 row: 'welds are not modelled (no readable weld geometry in SDS/2 files)'; no layout analysis behind the claim; class 1 ignores welds.",
    "SDS2 fixer", "Document the weld records found (or not) in mem/<n>; keep as info.",
    1285, "all")

add("v4 NaN placements / STEP syntax errors",
    "fixed_deployed",
    "v4: Binney 700 syntax errors + 140 unresolved references, Greenwood 1 NaN placement (REGRESSION.md). Live: 0 of 331 graded v5.x results carry step_load_errors; 41 v5.3 and 41 "
    "v5.4 re-runs on BOX-C: 0 load errors, 0 invalid. Remaining v4 STEPs are covered by the v4 re-run flaw.",
    "SDS2 fixer", "None beyond re-running v4 STEPs.", 0, "all")

add("Joists written as solid blocks (v4)",
    "fixed_deployed",
    "v5.x first-time results contain no joist_as_envelope_box; designation joists are joist_openweb_standin (137 models), JOIST members with non-joist sections remain boxes (24). v4 boxes "
    "persist in 318 reused/v4 models (see v4 re-run flaw).",
    "SDS2 fixer", "Extrude rolled sections for JOIST-typed members instead of boxing them.", 318, "7.0xx-7.6xx")

add("ZeroDivisionError / NaN end-point crashes (v4)",
    "fixed_deployed",
    "0 zerodivisionerror among v5.x results; v4 had 6 (audit-sds2-v5x fleet logs) and bf530885 (7.619) fell back to stage 1 on it.",
    "SDS2 fixer", "None.", 1, "7.4xx, 7.6xx")

add("Converter duplicates (same piece written for both members of a connection)",
    "fixed_deployed",
    "v5.3 0.1 in grid: BOX-C re-runs found 6 / 4 / 1 duplicates in v4 class-1 STEPs d6dfde1c / dfbfc59b / fba8adaf that v5.3 skips; v5.x manifests log removed duplicates (7.3xx 4,858, "
    "8.0xx 13,892 ...). v5.1/v5.2 results with near-duplicates (73 targeted) wait for the paused v5.3 rule.",
    "SDS2 fixer / builder", "Un-pause the v5.3 duplicate rule with the class-2 re-runs.", 73, "all")

out = {
    "slug": "sds2",
    "versions": bd + ex + special,
    "flaws": F,
}
json.dump(out, open('audit_sds2_structured.json', 'w'), indent=1)
print(len(out['versions']), len(F))
print(sum(len(json.dumps(x)) for x in F))
