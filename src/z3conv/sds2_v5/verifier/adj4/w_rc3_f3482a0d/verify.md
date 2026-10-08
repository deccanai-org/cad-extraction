# SDS2 -> STEP verification: f3482a0d_stage2.step

## Verdict: CORRECT (with warnings)

- G4 WARN: 44 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)

## Corpus tier: B (confirmed (internal checks))

- 20 of 4388 solids flagged (approx 20, joist_envelope 20)
- 492 guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)

Overall check status: WARN | evidence: mass | stage: piece | version 7.720 | solids 2,800

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.720, mem_idx_size=12906256, calibrated_slot=3600, slot_family=slot 3600, layout=slot=0xe10, type=0xd0c, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x200, sec_fmt=>h, roll=0x206, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - version 7.720 (slot 3600) not validated before; trust rests on M/E checks (EC-04) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=446, base=0xbc, byte_order=little, dims_at=0x1c, weight_at=0x44, votes=weight=283, dims=12, w_records=283, records=2250, aisc_checked=12, aisc_mismatch=[], w_plausible_share=0.9965 |  |
| D3 Section field sanity | **PASS** | structural=391, with_section_share=1, distinct_sections=272, top_section=[L10x10x1 1/8, 11], top_share=0.0281, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **NA** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0.0691, columns_vertical_share=1, beams_level_share=0.9958, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **NA** | members=391, outliers=19, outlier_share=0.0486, threshold_in=4335, policy=level=NOTE, cause=source, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - members far from the building (EC-15: scratch/stray members kept in the job) |
| D6 Section index vs main-piece name | **NA** | agreement=0, section_source=index, piece_name_path=slot=1024, name_off=960, sample_hits=353/400, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=2805, present=2805, missing=0, unexpected=0, shared_recorded_once=5, approximate_solids=20, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=2800, manifest_solids=2800 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=0.9905 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[6323, 1998, 560.9], decoded_span_in=[6335, 2080, 550.9], span_ratio=[0.998, 0.961, 1.018], centre_shift_in=[8.2, 4, 5] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=2754, median_ratio=1, within_tol_share=1, tol=0.15, p05=0.979, p95=1.033, by_family=L=[1053, 1.013], PL=[636, 1], W=[280, 1.033], BLT=[241, 1], RB=[235, 1.007], BPL=[181, 1], HSS=[42, 0.996], ROUN=[29, 0.994], not_compared=weighed as concrete=18 |  |
| M2 Open-web joists represented plausibly | **PASS** | joists=23, with_weight=23, median_mass_ratio=0.58, solid_block_share=0 |  |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=2800, touching_share=0.9261, isolated=207 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=928, on_parent_share=0.9957, off_parent=4, off_parent_touching_other_member=3, off_parent_confirmed_by_ifc=None, resolved_share=0.9989, basis=touching other member | 4 pieces sit on another member of the connection (EC-44), accepted on touching other member evidence |
| G4 Duplicate solids | **WARN** | duplicates=44, already_in_sds2_job=44, introduced_by_converter=0, share=0.01143, converter_examples=[], source_examples=[MISC #1363 / RB1/2 (piece 1235, inst 1) = MISC #1367 / RB1/2 (piece 1235, inst 1) (listed by the converter as SDS2's own), MISC #1363 / RB1/2 (piece 1235, inst 1) = MISC #1381 / RB1/2 (piece 1235, inst 1) (listed by the converter as SDS2's own), MISC #1363 / RB1/2 (piece 1235, inst 1) = MISC #1385 / RB1/2 (piece 1235, inst 1) (listed by the converter as SDS2's own), MISC #1368 / RB1/2 (piece 1235, inst 1) = MISC #1382 / RB1/2 (piece 1235, inst 1) (listed by the converter as SDS2's own), MISC #1371 / RB1/2 (piece 3318, inst 1) = MISC #1389 / RB1/2 (piece 3318, inst 1) (listed by the converter as SDS2's own), MISC #1372 / RB1/2 (piece 3318, inst 1) = MISC #1390 / RB1/2 (piece 3318, inst 1) (listed by the converter as SDS2's own), ...], policy=level=WARN, cause=source, verifier_status=FAIL, why=44 identical solid(s) placed twice by SDS2's own data (kept as stored) | 44 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies) |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=2800, rebuilt=2532, no_decoded_counterpart=268, within_0_1in=0.923, within_3in=0.9874, over_12in=1, median_err_in=0, p99_err_in=3.846 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
