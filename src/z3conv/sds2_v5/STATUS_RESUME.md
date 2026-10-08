# SDS2 converter work: status for resume (2026-10-02 ~23:50Z)

## Shipped (s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/, handed to builder a965852984ca96fd8)

| version | content | sha (start) |
|---|---|---|
| v5.5.0 | joist DSLH | 85e11587 |
| v5.5.3 | absurd-extent / BLT bolts / reference models | 706e1289 |
| v5.5.4 | 7.x pieces, CSU, `--nc1`, open surfaces | 8e82ce7b |
| v5.5.5 | unplaced_pieces_proof | 2a6e5b68 |
| v5.5.6 | grating / rods (_pfix merge; gratings exact when weight within 3 %) | ef1952bf |
| v5.5.7 | turned-piece sanity, no_piece_file, repair label strip, face-set open surfaces, stub-member calibration, verify budget | 707ada97 |
| v5.5.8 | repair-stage-only spike/keyhole split, _pfix 7x rebase, grating holes, _name_dia, invalid_parts_excluded | 7fab6793 |
| v5.5.9 | joist stand-ins as local parts + placement; index_proof; untyped index -> member-file placement | f5dd227e |
| v5.5.10-rc | canary: read-back repair acts on placed copies; rods rewritten local + placement; readback_repair | 2572b116 |
| v5.5.11-rc | WITHDRAWN (dropped one rod of X braces) | 364281d5 |
| v5.5.11-rc2 | held: removed a main-main twin on TYSONS | c439ccf8 |
| v5.5.11-rc3 | held: twin rule fired on shared piece ids (GMS_Test) | 8d74a0ed |
| v5.5.11-rc4 | canary: owner-attributed main-material listings, header-only twins + rc3 content | b7cab511 |

Trees: rel554 / rel555 / rel556 / rel557 / rel558 / rel559.

## Now (BOX-C terminated; BOX-B i-076e73980707c7dbe self-shuts ~22:47Z; no cleanup needed per coordinator)
- SSM to BOX-B is blocked for me (classifier). The coordinator says: don't retry SSM or try other credentials.
  S3 reads with bim work. Release uploads still go through annotationprod-publish to _control/z3conv/sds2/.
- v5.5.9 shipped 2026-10-02 18:37Z and handed to builder. Spectrum + SOCORRO v5.5.8 confirmations sent.
- Joist round-trip (v558b -> v559a): excluded 60 -> 0 (0535bdbb), 61 -> 0 (4c381a54); all joists valid; pieces, volume
  and weight identical. Both jobs remain class 0: 7 / 3 non-joist parts invalid after read-back (RB1/2 rods on joist
  members, e.g. JOIST #182 piece 20247; open-surface plates). The read-back repair names them but does not match the
  names, so nothing is rewritten or dropped (same in v5.5.8).
- v5.5.10-rc (rel5510, sha 2572b116) uploaded as sds2-step-pipeline-v5.5.10-rc.zip and handed to the builder as a
  canary: best-of on 0535bdbb, 4c381a54 and the 5 controls. The builder promotes it only if controls are identical
  and both jobs leave class 0 with every part listed.
  - Cause: repair names were ignored for placed copies (add_exact flat branch; assembly-check `bad` branch ran
    before the DROP check). The parts are RB1/2 special_primitive rods, not the open plates.
  - Fix: repair_action() (drop first, any form); pass 1 rewrites world-built rods as local part + placement;
    manifest readback_repair {rewritten, left_out}; the log prints 20 names.
  - Tests: scratch/test_v5510_repair.py <decode> (exact names, 200-rod round trip: 19 flat invalid, 0 component);
    AGNEWS-R smoke (base identical, force 5 rewritten, drop 5 listed; v5.5.9 drops 2).
- If the canary passes, the builder promotes it. If it fails, read the builder's results and fix in rel5510.

## SDS2 verifier review (teammate's sds2_step_verifier v1.3.3), 2026-10-02
- Work dir: verifier/ (fleet_index.json, out/<id8>/ fleet outputs, jobs/<id8>/, raw/ = unmodified runs, ad/ = adapted).
- Delivered to _control/z3conv/verify/: adapter_sds2.py (builder contract) + sds2/ (verifier unmodified minus samples/,
  verify_v55.py format adapter + 2 reported decoder fixes, stage_gt.py, grader_patch_sds2.py, sample_ids.json).
- Results: 84ed6ebb / afea6a26 1A agree; 6eeedc27 demoted (G4 real 2 repeats; G2/G3 false positive); 8d3cfac8 G4 real;
  ca1a958a M1 CVN 0.79x; Greenwood M2 placeholder weights + E2/E3 other revision.
- Proposed next: v5.5.11 counts.duplicate_placements (exact same part + placement; listed, never removed).

## v5.5.11-rc / adapter policy (2026-10-02 ~21:15Z)
- rel5511 = rel5510 + duplicate handling (to_step2 geo_seen / geo_name, _same_place; manifest converter_duplicates_removed,
  source_duplicate_placements, counts.duplicate_placements). Local read-back runs in /tmp/sds2b/conv/rel5511v/.
- Adapter policy in verifier/deliver/sds2/verify_v55.py (install_policy); adapter_sds2.py causes pipeline|source|
  by_design|verifier|ground_truth_other_revision. Live at _control/z3conv/verify/ (builder worker syncs it).
- Pending: builder canary of v5.5.11-rc; coordinator OK on patch B and on E-FAIL-blocks-class-1 interpretation.
- Next: builder-relayed groups: Nantucket standard_constructionerror (9 rows) and steel_weight_mismatch (8 rows).

## Verify adapters / rc3 (2026-10-02 ~22:40Z)
- Live/versioned at _control/z3conv/verify/: adapter_sds2.py (v2), _v3 (d4f0feb7, builder on it), _v4 (679a831e),
  _v5 (c481f4e2: header-only main twins). Builder asked to switch to v5.
- Fleet verify results: bim .../_state/conv/verify/results/sds2-*.json (local copy verifier/fleetver/).
- rc3 local evidence: /tmp/sds2b/rc3v, /tmp/sds2b/m1b (manifests). Canary requested incl. Nantucket, 713dae63, 8f39034b,
  80ea451b, 1b6216e0 (a1a87e6b if a slot is free).
- Open: Mueller dominant outlier '8x852' (fleet QA should use ratio_without_outliers); IRVINE needs fleet rerun.

## Findings left open
- HSS family ~0.93 and WS ~0.5: SDS2 weight / ring conventions, not converter bugs.
- W +17 %: tagged approximate extrusions.
- Reference models with unlinked frames (placement blocks carry GUID + colour, no piece id): class 3 R with proof.
- 7.x approx left: grating that doesn't build, non-manifold tubes, plate B-rep vs bar table entries, absent piece
  files.

## Earlier: held (done; v5.5.8 shipped)
- v5.5.8 = rel558 = v5.5.7 + every part left out by the read-back repair listed (untyped " #<n>" labels were
  unparsed), plus the `invalid_parts_excluded` count and class reason.
- To ship: on BOX-C, run agentjob2/f558.sh (Spectrum t_319570f4, AGNEWS-T, GMS; v558a.tgz, which may need
  re-uploading). Then zip rel558, upload to _control/z3conv/sds2/ and message the builder.
- rel557 was restored from the shipped v5.5.7 zip.

## Results read after v5.5.7 shipped
- Spectrum: class 0 -> 2.
- TEMP JOB RGK: +1,028 exact pieces.
- Still to read: c3 batch (32/52 dirs); f557h (ebce209f on final v5.5.7).

## rel558 contents (prepared locally 2026-10-02; box regression waits for the owner's login)
1. The spike / keyhole split is repair-stage only. brep.py is the `_pfix` 7x patch's brep.py plus the v5.5.4
   boundary_loops / rims_only helpers. It fixes the v5.5.4+ loss of DSCC W10x12 #5513 and SOCORRO HSS5x2x5/16 #3492.
2. Rebased from `_pfix` 7x:
   - repair stage (first-vertex keyhole bridge, cross-loop opposite-edge cancel, ring caps, isolated / sliver /
     coplanar / weld);
   - negative-weight |w|;
   - tube identity with the table-length check;
   - brep_repairs manifest section.
   Section-area identity: v5.5.4's _section_ok is kept as the single rule.
3. `grating._on_stored_face` honours holes in the covering face (unit-tested: solid part / inside hole / around hole).
4. `_name_dia` reads fractions before 'x' ('RB3/4x12' -> 0.75).
5. Every part left out by the read-back repair is listed, with `invalid_parts_excluded`.

Not taken: sds2-weights-failures, sds2-pieces-not-built (`_nest_voids`).

Local check (Mac, light): Novelis exact pieces are identical, 935 / 935 in both v5.5.7 and rel558. Cats Rail 7.312:
4,952 -> 4,967 exact (+15 from the repair stage: keyhole split + isolated faces dropped), 0 lost.

### After login
- Upload rel558 as v558b.tgz.
- Regression on BOX-C:
  - control (GMS, AGNEWS-R, AGNEWS-T, TYSONS, METHODIST, 19002);
  - Spectrum t_319570f4;
  - DSCC (DSCC_JOB_ef345b) and SOCORRO (SOCORRO_ISD_JOB_8566ee): the two regression pieces must be exact again;
  - IFC_MHP 1f2578, Revit_MHP 4a9554 (expect 2B -> 1A);
  - 10 World Trade c5f1d1.
- Then ship v5.5.8.

## class3_review batch results (c3, run on v557b = v5.5.7 without its repair-label fix)
- converter_wrote_nothing (22): proven class 3 (20 reference models with unlinked frames, 2 with no geometry).
- step_invalid_solids (11):
  - Seven 7.516 / 7.613 jobs stay class 0 with 3-9 invalid after repair pass 2.
  - On the 7.516 jobs, most invalid parts are open-web JOIST stand-ins that read back invalid. Pass 2 drops most of
    them; about 7 remain.
  - NEXT: check joist.py stand-in solids for read-back validity (a converter defect), and re-run on v5.5.7 / v5.5.8
    (label fix + exclusion listing).
- no_proof_calibration_fail (7): member files are present but calibration finds 0-2 type markers.
  - 18e77755 Forsyth 7.331, 58c96961 / 6eeedc27 7.243, 7fa1c983 7.618, 94b59c49 7.132, e1304b91 7.613, 2ac238d7
    (empty DWF).
  - NEXT: diagnose (likely stub member files / sparse layouts, as 5eed44fe).
- other: 8 hit the 2 h test timeout (big jobs). 79e84a02 and ed8dea96 are class 2 B; 90b89fcf and f3e696bf are class 2 R.
