# SDS2 -> STEP verification: OMEMO_JOB_afea6a_stage2.step

## Verdict: CORRECT (with warnings)

- D1 WARN: piece decoding is only validated on 7.2xx; 7.3xx pieces are judged by G5/E1/M1 (EC-05)
- D6 WARN: section index path broken; sections taken from piece names (EC-47)

## Corpus tier: A (confirmed (internal checks))


Overall check status: WARN | evidence: mass | stage: piece | version 7.312 | solids 341

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **WARN** | jsetup_version=7.312, mem_idx_size=2950144, calibrated_slot=2944, slot_family=7.3xx, layout=slot=0xb80, type=0xa78, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x1a0, sec_fmt=>h, roll=0x1a6, decode_error=None | piece decoding is only validated on 7.2xx; 7.3xx pieces are judged by G5/E1/M1 (EC-05) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=274, dims=12, w_records=274, records=1701, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=67, with_section_share=1, distinct_sections=9, top_section=[HSS5x5x1/4, 32], top_share=0.4776, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **PASS** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=1, beams_level_share=1 |  |
| D5 Stray members (spatial outliers) | **PASS** | members=67, outliers=0, outlier_share=0, threshold_in=4453 |  |
| D6 Section index vs main-piece name | **WARN** | agreement=0, section_source=piece_name (index path broken), piece_name_path=slot=902, name_off=302, sample_hits=111/111 | section index path broken; sections taken from piece names (EC-47) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=341, present=341, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=341, manifest_solids=341 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[2315, 805.3, 186.3], decoded_span_in=[2315, 806.3, 170.2], span_ratio=[1, 0.999, 1.094], centre_shift_in=[0.2, 0.5, 8] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=341, median_ratio=1, within_tol_share=1, tol=0.15, p05=0.999, p95=1.036, by_family=WS=[228, 1], PL=[46, 1], HSS=[35, 0.999], W=[32, 1.036], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=341, touching_share=1, isolated=0 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=230, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0 |  |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=341, rebuilt=113, no_decoded_counterpart=228, within_0_1in=0.9558, within_3in=0.9912, over_12in=0, median_err_in=0, p99_err_in=1 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
