# SDS2 -> STEP verification: ca1a958a_stage2.step

## Verdict: CORRECT (with warnings)

- G4 WARN: 23 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)

## Corpus tier: B (pending evidence)

- 96 of 1569 solids flagged (approx 82, joist_envelope 14)
- 271 guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)

Overall check status: WARN | evidence: mass | stage: piece | version 7.312 | solids 828

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.312, mem_idx_size=2950144, calibrated_slot=2944, slot_family=7.3xx, layout=slot=0xb80, type=0xa78, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x266, sec_fmt=>h, roll=0x26c, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - piece decoding is only validated on 7.2xx; 7.3xx pieces are judged by G5/E1/M1 (EC-05) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=274, dims=12, w_records=274, records=1701, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=173, with_section_share=1, distinct_sections=59, top_section=[W12x252, 22], top_share=0.1272, beam_family_ok=0.9922 |  |
| D4 Work-line / roll field sanity | **NA** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=1, beams_level_share=0.5312, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **PASS** | members=173, outliers=0, outlier_share=0, threshold_in=2524 |  |
| D6 Section index vs main-piece name | **NA** | agreement=0, section_source=index, piece_name_path=slot=902, name_off=302, sample_hits=289/399, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **NA** | expected_pieces=865, present=865, missing=0, unexpected=0, shared_recorded_once=52, approximate_solids=81, member_envelopes=15, missing_by_kind= | NOTE (every missing piece is listed by the converter's own manifest, or only approximate solids / unexpected items (its piece decoder is an older copy of the converter's)); verifier: WARN - 0 expected items are missing from the STEP |
| S1 Solid count vs manifest | **PASS** | step_solids=828, manifest_solids=828 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=0.982 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[1558, 1634, 276.6], decoded_span_in=[1402, 1637, 284.9], span_ratio=[1.111, 0.998, 0.971], centre_shift_in=[77.5, 1.7, 4.1] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=732, median_ratio=1, within_tol_share=1, tol=0.15, p05=0.997, p95=1.021, by_family=PL=[245, 1], HSS=[160, 0.999], FB=[131, 1], L=[125, 1.015], RB=[27, 1.007], W=[22, 1.032], WS=[18, 1], BLT=[4, 1], not_compared= |  (judged on the parts claimed exact; all parts FAIL only because of approximate parts (already class 2)) |
| M2 Open-web joists represented plausibly | **NA** | joists=14, with_weight=0, median_mass_ratio=None, solid_block_share=None, policy=level=NOTE, cause=pipeline, verifier_status=WARN, why=every joist solid is a tagged stand-in (class 2 already) | NOTE (every joist solid is a tagged stand-in (class 2 already)); verifier: WARN - joists present but no recorded weight to judge them |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=828, touching_share=0.994, isolated=5 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=445, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **WARN** | duplicates=23, already_in_sds2_job=23, introduced_by_converter=0, share=0.01329, converter_examples=[], source_examples=[COLUMN #10 / PL1/2x8 (piece 462, inst 1) = MISC #298 / PL1/2x8 (piece 462, inst 1) (listed by the converter as SDS2's own), COLUMN #12 / PL1/2x8 (piece 462, inst 1) = MISC #304 / PL1/2x8 (piece 462, inst 1) (listed by the converter as SDS2's own), COLUMN #17 / PL3/4x8 (piece 485, inst 1) = MISC #328 / PL3/4x8 (piece 485, inst 1) (listed by the converter as SDS2's own), COLUMN #23 / FB1/4x6 (piece 143, inst 2) = COLUMN #24 / FB1/4x6 (piece 705, inst 1) (listed by the converter as SDS2's own), COLUMN #25 / FB1/4x6 (piece 143, inst 2) = COLUMN #26 / FB1/4x6 (piece 705, inst 1) (listed by the converter as SDS2's own), COLUMN #27 / FB1/4x6 (piece 143, inst 2) = COLUMN #28 / FB1/4x6 (piece 705, inst 1) (listed by the converter as SDS2's own), ...], policy=level=WARN, cause=source, verifier_status=FAIL, why=23 identical solid(s) placed twice by SDS2's own data (kept as stored) | 23 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies) |
| G5 Piece solids match decoded placement (independent rebuild) | **NA** | solids=813, rebuilt=656, no_decoded_counterpart=157, within_0_1in=0.5793, within_3in=0.9284, over_12in=4, median_err_in=0, p99_err_in=9.192 | NOTE (rebuilt from each piece's topology vertices: 1.0 within 3 in (the verifier's raw vertex records include non-geometry points, EC-45)); verifier: WARN - STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error) |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
