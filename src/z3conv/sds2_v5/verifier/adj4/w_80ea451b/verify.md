# SDS2 -> STEP verification: 80ea451b_stage2.step

## Verdict: CORRECT (with warnings)

- G4 WARN: 1 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: PASS

## Corpus tier: B (confirmed (internal checks))

- 12 of 8387 solids flagged (approx 12)
- 5442 guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)

Overall check status: WARN | evidence: mass | stage: piece | version 7.021 | solids 2,623

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.021, mem_idx_size=1313536, calibrated_slot=1280, slot_family=slot 1280, layout=slot=0x500, type=0x44, p1=0x10a, p2=0x13c, pt_fmt=>f4, sec=0x1b2, sec_fmt=>h, roll=0x356, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - version 7.021 (slot 1280) not validated before; trust rests on M/E checks (EC-04) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=178, base=0x4e, byte_order=big, dims_at=0x1a, weight_at=0x2e, votes=weight=300, dims=12, w_records=314, records=1823, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **NA** | structural=759, with_section_share=1, distinct_sections=305, top_section=[W21x147, 64], top_share=0.0843, beam_family_ok=0.8148, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - some members lack a plausible section |
| D4 Work-line / roll field sanity | **NA** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=0.6849, beams_level_share=0.8596, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **PASS** | members=759, outliers=0, outlier_share=0, threshold_in=5378 |  |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=index, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=2621, present=2621, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=10, member_envelopes=2, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=2623, manifest_solids=2623 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=0.9985, positive_volume_share=1, single_solid_share=0.9985 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[2738, 1971, 1050], decoded_span_in=[2739, 1971, 1050], span_ratio=[1, 1, 1], centre_shift_in=[0.1, 0, 0] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=1958, median_ratio=0.988, within_tol_share=0.9959, tol=0.15, p05=0.96, p95=1.043, by_family=L=[1012, 0.963], W=[429, 1.023], HSS=[214, 0.997], PIPE=[123, 0.99], PL=[107, 0.987], FL=[54, 1], BPL=[15, 0.98], WT=[4, 0.816], not_compared= |  (judged on the parts claimed exact; all parts FAIL only because of approximate parts (already class 2)) |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=2623, touching_share=0.9992, isolated=2 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=1858, on_parent_share=0.9995, off_parent=1, off_parent_touching_other_member=1, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member | 1 pieces sit on another member of the connection (EC-44), accepted on touching other member evidence |
| G4 Duplicate solids | **WARN** | duplicates=1, already_in_sds2_job=1, introduced_by_converter=0, share=0.00038, converter_examples=[], source_examples=[COLUMN #523 / HSS18x6x1/2 (piece 428, inst 1) = COLUMN #523 / HSS18x6x1/2 (piece 428, inst 2) (listed by the converter as SDS2's own)], policy=level=WARN, cause=source, verifier_status=PASS, why=1 identical solid(s) placed twice by SDS2's own data (kept as stored) | 1 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: PASS |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=2621, rebuilt=2621, no_decoded_counterpart=0, within_0_1in=0.9515, within_3in=0.9771, over_12in=12, median_err_in=0, p99_err_in=6.651 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
