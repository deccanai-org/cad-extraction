# SDS2 -> STEP verification: GOPAL_TRAINING_FAB_d65730_stage2.step

## Verdict: INCORRECT

- S4 FAIL: model scale is off (EC-19: inches written as mm or similar)

## Corpus tier: EXCLUDED

- checks failed: S4

Overall check status: FAIL | evidence: mass | stage: piece | version 7.312 | solids 47

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.312, mem_idx_size=2950144, calibrated_slot=2944, slot_family=7.3xx, layout=slot=0xb80, type=0xa78, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x200, sec_fmt=>h, roll=0x206, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - piece decoding is only validated on 7.2xx; 7.3xx pieces are judged by G5/E1/M1 (EC-05) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=274, dims=12, w_records=274, records=1701, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=2, with_section_share=1, distinct_sections=2, top_section=[W40x327, 1], top_share=0.5, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **PASS** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=1, beams_level_share=1 |  |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=0, section_source=index, piece_name_path=slot=902, name_off=302, sample_hits=44/44, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=48, present=48, missing=0, unexpected=0, shared_recorded_once=1, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=47, manifest_solids=47 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **FAIL** | file_unit=MM, span_in=[2704, 1710, 51], decoded_span_in=[252, 448, 1], span_ratio=[10.73, 3.818, 51], centre_shift_in=[529.3, 467.9, 18.5] | model scale is off (EC-19: inches written as mm or similar) |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=47, median_ratio=1, within_tol_share=1, tol=0.15, p05=1, p95=1, by_family=PL=[45, 1], W=[2, 1.002], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=47, touching_share=1, isolated=0 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=4, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0, converter_examples=[], source_examples=[], policy=level=PASS, cause=pipeline, verifier_status=PASS, why= |  |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=47, rebuilt=4, no_decoded_counterpart=43, within_0_1in=1, within_3in=1, over_12in=0, median_err_in=0, p99_err_in=0 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
