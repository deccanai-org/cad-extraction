# SDS2 -> STEP verification: 00000_Temp_J_V2017.13_7fa1c9_stage2.step

## Verdict: CORRECT


## Corpus tier: A (pending evidence)


Overall check status: PASS | evidence: internal | stage: piece | version 7.618 | solids 3

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.618, mem_idx_size=3411064, calibrated_slot=None, slot_family=None, layout=, decode_error=job has only 0 members in mem_idx - empty or placeholder job, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - layout auto-calibration failed (EC-01/EC-06): cannot decode this job |
| D2 Shape table (job_mtrl) sanity | **NA** | layout=record=416, base=0x59, byte_order=little, dims_at=0x1c, weight_at=0x44, votes=weight=300, dims=12, w_records=316, records=1870, aisc_checked=0, aisc_mismatch=[], w_plausible_share=1, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - could not confirm shape dims against AISC |
| D3 Section field sanity | **NA** | policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - no structural members decoded (EC-08: wrong type offset) |
| D4 Work-line / roll field sanity | **NA** | policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - no structural members decoded (EC-08) |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=None, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=3, present=3, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=3, manifest_solids=3 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **NA** | file_unit=MM, span_in=[30, 6, 3.5], decoded_span_in=[1, 1, 1], span_ratio=[30, 6, 3.5], centre_shift_in=[75, 3, 1198] | no reference extent: no decoded piece boxes and no decoded members (adapter) |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **NA** | all_parts=status=NA, reason=no recorded weights to compare, families_off=None, within_tol_share=None, compared=None, policy=level=NA, cause=pipeline, verifier_status=NA, why=judged on the parts claimed exact | no recorded weights to compare |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **NA** |  |  |
| G3 Connection pieces sit on their parent member | **NA** |  |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0, converter_examples=[], source_examples=[], policy=level=PASS, cause=pipeline, verifier_status=PASS, why= |  |
| G5 Piece solids match decoded placement (independent rebuild) | **NA** | solids=3, rebuilt=3, no_decoded_counterpart=0, within_0_1in=0, within_3in=0.3333, over_12in=0, median_err_in=4.25, p99_err_in=5.169 | NOTE (rebuilt from each piece's topology vertices: 1.0 within 3 in (the verifier's raw vertex records include non-geometry points, EC-45)); verifier: FAIL - STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error) |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
