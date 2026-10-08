# SDS2 -> STEP verification: e222e6b6_stage2.step

## Verdict: CORRECT (with warnings)

- G4 WARN: 653 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)

## Corpus tier: B (pending evidence)

- 107 of 12940 solids flagged (approx 29, joist_envelope 78)
- 2072 guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)

Overall check status: WARN | evidence: mass | stage: piece | version 7.312 | solids 5,243

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.312, mem_idx_size=10554496, calibrated_slot=2944, slot_family=7.3xx, layout=slot=0xb80, type=0xa78, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x1fc, sec_fmt=>h, roll=0x202, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - piece decoding is only validated on 7.2xx; 7.3xx pieces are judged by G5/E1/M1 (EC-05) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=274, dims=12, w_records=274, records=1701, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=853, with_section_share=1, distinct_sections=42, top_section=[W18x40, 199], top_share=0.2333, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **PASS** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=1, beams_level_share=1 |  |
| D5 Stray members (spatial outliers) | **NA** | members=853, outliers=101, outlier_share=0.1184, threshold_in=5143, policy=level=NOTE, cause=source, verifier_status=FAIL, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - members far from the building (EC-15: scratch/stray members kept in the job) |
| D6 Section index vs main-piece name | **NA** | agreement=0.8803, section_source=index, piece_name_path=slot=902, name_off=302, sample_hits=393/393, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=5585, present=5585, missing=0, unexpected=0, shared_recorded_once=434, approximate_solids=15, member_envelopes=92, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=5243, manifest_solids=5243 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=0.9989, positive_volume_share=1, single_solid_share=0.9822 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[1.456e+04, 3262, 550], decoded_span_in=[1.444e+04, 3299, 550], span_ratio=[1.008, 0.989, 1], centre_shift_in=[61.5, 18.5, 0] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=4875, median_ratio=1, within_tol_share=1, tol=0.15, p05=0.94, p95=1.025, by_family=PL=[1520, 1], L=[1183, 0.974], C=[651, 1.007], WS=[531, 1], HSS=[509, 0.998], W=[466, 1.025], BPL=[13, 1], RB=[1, 1.007], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** | joists=78, with_weight=78, median_mass_ratio=3.88, solid_block_share=0.7821, policy=level=NOTE, cause=pipeline, verifier_status=FAIL, why=every joist solid is a tagged stand-in (class 2 already) | NOTE (every joist solid is a tagged stand-in (class 2 already)); verifier: FAIL - open-web joists written as solid blocks (EC-34): mass is 100x+ the real joist |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=5243, touching_share=0.9964, isolated=19 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=3140, on_parent_share=0.9984, off_parent=5, off_parent_touching_other_member=5, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member | 5 pieces sit on another member of the connection (EC-44), accepted on touching other member evidence |
| G4 Duplicate solids | **WARN** | duplicates=653, already_in_sds2_job=653, introduced_by_converter=0, share=0.1007, converter_examples=[], source_examples=[MISC #725 / WS1/2 (piece 2180, inst 1) = COLUMN #1546 / WS1/2 (piece 2292, inst 3) (listed by the converter as SDS2's own), MISC #725 / WS1/2 (piece 2180, inst 2) = COLUMN #1546 / WS1/2 (piece 2292, inst 1) (listed by the converter as SDS2's own), MISC #725 / WS1/2 (piece 2180, inst 3) = COLUMN #1546 / WS1/2 (piece 2292, inst 2) (listed by the converter as SDS2's own), MISC #727 / WS1/2 (piece 2180, inst 1) = COLUMN #1538 / WS1/2 (piece 2292, inst 1) (listed by the converter as SDS2's own), MISC #727 / WS1/2 (piece 2180, inst 2) = COLUMN #1538 / WS1/2 (piece 2292, inst 3) (listed by the converter as SDS2's own), MISC #727 / WS1/2 (piece 2180, inst 3) = COLUMN #1538 / WS1/2 (piece 2292, inst 2) (listed by the converter as SDS2's own), ...], policy=level=WARN, cause=source, verifier_status=FAIL, why=653 identical solid(s) placed twice by SDS2's own data (kept as stored) | 653 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies) |
| G5 Piece solids match decoded placement (independent rebuild) | **NA** | solids=5151, rebuilt=4599, no_decoded_counterpart=552, within_0_1in=0.7023, within_3in=0.9195, over_12in=50, median_err_in=0, p99_err_in=12.36 | NOTE (rebuilt from each piece's topology vertices: 1.0 within 3 in (the verifier's raw vertex records include non-geometry points, EC-45)); verifier: WARN - STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error) |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
