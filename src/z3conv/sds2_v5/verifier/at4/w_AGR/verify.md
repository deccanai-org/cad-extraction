# SDS2 -> STEP verification: AGR_stage2.step

## Verdict: CORRECT (with warnings)

- S2 WARN: 3.7% of non-fastener pieces are multi-body solids (valid and closed)
- G4 WARN: 19 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)

## Corpus tier: B (confirmed (internal checks))

- 21 of 919 solids flagged (approx 3, joist_envelope 18)
- 65 guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)

Overall check status: WARN | evidence: mass | stage: piece | version 7.331 | solids 803

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.331, mem_idx_size=2950144, calibrated_slot=2944, slot_family=7.3xx, layout=slot=0xb80, type=0xa78, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x200, sec_fmt=>h, roll=0x206, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - piece decoding is only validated on 7.2xx; 7.3xx pieces are judged by G5/E1/M1 (EC-05) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=274, dims=12, w_records=274, records=1709, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **NA** | structural=53, with_section_share=1, distinct_sections=42, top_section=[, 6], top_share=0.1132, beam_family_ok=0.6842, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - most members lack a plausible section (EC-10) |
| D4 Work-line / roll field sanity | **NA** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0.0566, columns_vertical_share=1, beams_level_share=1, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **PASS** | members=53, outliers=0, outlier_share=0, threshold_in=1477 |  |
| D6 Section index vs main-piece name | **NA** | agreement=0, section_source=index, piece_name_path=slot=902, name_off=302, sample_hits=155/165, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=843, present=843, missing=0, unexpected=0, shared_recorded_once=58, approximate_solids=3, member_envelopes=18, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=803, manifest_solids=803 |  |
| S2 B-rep validity | **WARN** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=0.9633, policy=level=WARN, cause=by_design, verifier_status=WARN, why= | 3.7% of non-fastener pieces are multi-body solids (valid and closed) |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[823.8, 694.8, 259], decoded_span_in=[827.2, 696.2, 256.4], span_ratio=[0.996, 0.998, 1.01], centre_shift_in=[1.2, 0.2, 1.7] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=782, median_ratio=1, within_tol_share=0.9527, tol=0.15, p05=0.859, p95=1.008, by_family=PL=[325, 0.996], BLT=[253, 1], HSS=[127, 0.996], RB=[59, 1.008], C=[17, 1.016], W=[1, 1.041], not_compared= |  |
| M2 Open-web joists represented plausibly | **PASS** | joists=18, with_weight=18, median_mass_ratio=0.02, solid_block_share=0 |  |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=803, touching_share=0.9988, isolated=1 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=623, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **WARN** | duplicates=19, already_in_sds2_job=19, introduced_by_converter=0, share=0.02117, converter_examples=[], source_examples=[BEAM #45 / C4x5.4 (piece 547, inst 1) = BEAM #163 / C4x5.4 (piece 257, inst 1) (listed by the converter as SDS2's own), BEAM #46 / C4x5.4 (piece 548, inst 1) = BEAM #164 / C4x5.4 (piece 94, inst 1) (listed by the converter as SDS2's own), BEAM #47 / C4x5.4 (piece 549, inst 1) = BEAM #165 / C4x5.4 (piece 258, inst 1) (listed by the converter as SDS2's own), BEAM #48 / HSS4x4x1/4 (piece 563, inst 1) = BEAM #166 / HSS4x4x1/4 (piece 259, inst 1) (listed by the converter as SDS2's own), BEAM #49 / HSS4x4x1/4 (piece 563, inst 1) = BEAM #167 / HSS4x4x1/4 (piece 259, inst 1) (listed by the converter as SDS2's own), MISC #50 / HSS3x1 1/2x1/4 (piece 550, inst 1) = MISC #168 / HSS3x1 1/2x1/4 (piece 222, inst 1) (listed by the converter as SDS2's own), ...], policy=level=WARN, cause=source, verifier_status=FAIL, why=19 identical solid(s) placed twice by SDS2's own data (kept as stored) | 19 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies) |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=785, rebuilt=470, no_decoded_counterpart=315, within_0_1in=0.8255, within_3in=0.9766, over_12in=1, median_err_in=0, p99_err_in=3.25 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
