# SDS2 -> STEP verification: CMC_Greenville_SeedJob_84ed6e_stage2.step

## Verdict: CORRECT (with warnings)

- D1 FAIL: jsetup says 7.245 but slot size 2944 belongs to 7.3xx (EC-02)
- D4 WARN: some work points / rolls implausible (EC-11/EC-14)
- D6 FAIL: section index disagrees with the piece names (EC-47: index off by one / wrong field)

## Corpus tier: A (confirmed (internal checks))

- verifier's member decoder is unreliable for this job (D-checks); piece checks decide

Overall check status: FAIL | evidence: mass | stage: piece | version 7.245 | solids 36

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **FAIL** | jsetup_version=7.245, mem_idx_size=2950144, calibrated_slot=2944, slot_family=7.3xx, layout=slot=0xb80, type=0xa78, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x200, sec_fmt=>h, roll=0x206, decode_error=None | jsetup says 7.245 but slot size 2944 belongs to 7.3xx (EC-02) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=300, dims=12, w_records=316, records=1831, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=12, with_section_share=1, distinct_sections=6, top_section=[W36x210, 4], top_share=0.3333, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **WARN** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0.3333, columns_vertical_share=1, beams_level_share=1 | some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **PASS** | members=12, outliers=0, outlier_share=0, threshold_in=954 |  |
| D6 Section index vs main-piece name | **FAIL** | agreement=0, section_source=index, piece_name_path=slot=902, name_off=302, sample_hits=12/12 | section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=36, present=36, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=36, manifest_solids=36 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[248.3, 250.1, 204], decoded_span_in=[248.3, 250.1, 204], span_ratio=[1, 1, 1], centre_shift_in=[0, 0, 0] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=36, median_ratio=1, within_tol_share=1, tol=0.15, p05=0.924, p95=1.052, by_family=L=[16, 0.925], W=[12, 1.034], PL=[8, 1], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=36, touching_share=1, isolated=0 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=24, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0 |  |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=36, rebuilt=36, no_decoded_counterpart=0, within_0_1in=1, within_3in=1, over_12in=0, median_err_in=0, p99_err_in=0 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
