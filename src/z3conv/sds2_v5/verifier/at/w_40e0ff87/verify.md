# SDS2 -> STEP verification: 50B_Temp_Job_40e0ff_stage2.step

## Verdict: CORRECT (with warnings)

- D4 WARN: some work points / rolls implausible (EC-11/EC-14)
- D6 FAIL: section index disagrees with the piece names (EC-47: index off by one / wrong field)
- S4 WARN: model extent differs from the decoded work points

## Corpus tier: B (confirmed (internal checks))

- 2 of 172 solids flagged (approx 2)
- 11 guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)
- verifier's member decoder is unreliable for this job (D-checks); piece checks decide

Overall check status: FAIL | evidence: mass | stage: piece | version 7.243 | solids 82

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **PASS** | jsetup_version=7.243, mem_idx_size=2499244, calibrated_slot=2494, slot_family=7.2xx, layout=slot=0x9be, type=0x988, p1=0x112, p2=0x172, pt_fmt=>f8, sec=0x1d8, sec_fmt=>h, roll=0x1de, decode_error=None |  |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=300, dims=12, w_records=316, records=2066, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=30, with_section_share=1, distinct_sections=30, top_section=[, 1], top_share=0.0333, beam_family_ok=0.9474 |  |
| D4 Work-line / roll field sanity | **WARN** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0.0667, columns_vertical_share=1, beams_level_share=1 | some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **PASS** | members=30, outliers=0, outlier_share=0, threshold_in=7561 |  |
| D6 Section index vs main-piece name | **FAIL** | agreement=0, section_source=index, piece_name_path=slot=852, name_off=302, sample_hits=39/39 | section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=81, present=81, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=1, member_envelopes=1, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=82, manifest_solids=82 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **WARN** | file_unit=MM, span_in=[3156, 1544, 372], decoded_span_in=[2478, 515.5, 372], span_ratio=[1.273, 2.994, 1], centre_shift_in=[338.7, 514, 0] | model extent differs from the decoded work points |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=81, median_ratio=1, within_tol_share=1, tol=0.15, p05=0.911, p95=1.06, by_family=PL=[22, 1], L=[20, 0.911], W=[19, 1.032], WS=[12, 1], FL=[3, 0.938], HSS=[2, 1.012], WT=[2, 1.023], ROUN=[1, 0.93], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=82, touching_share=0.939, isolated=5 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=42, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0 |  |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=81, rebuilt=61, no_decoded_counterpart=20, within_0_1in=0.9344, within_3in=0.9836, over_12in=0, median_err_in=0, p99_err_in=2.257 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
