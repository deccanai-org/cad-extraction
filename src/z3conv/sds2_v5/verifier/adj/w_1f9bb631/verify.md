# SDS2 -> STEP verification: Sturbridge_Noble_Rails_1f9bb6_stage2.step

## Verdict: INCORRECT

- G4 FAIL: 4 repeat solid(s) made by the converter (one SDS2 piece written twice); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)

## Corpus tier: A (confirmed (internal checks))

- 4 exact duplicate solids written by the converter: ship the de-duplicated copy (--dedup-out), not the original (G4)

Overall check status: FAIL | evidence: mass | stage: piece | version 7.619 | solids 189

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.619, mem_idx_size=3411064, calibrated_slot=None, slot_family=None, layout=, decode_error=job has only 2 members in mem_idx - empty or placeholder job, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - layout auto-calibration failed (EC-01/EC-06): cannot decode this job |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=406, base=0x10e, byte_order=little, dims_at=0x1c, weight_at=0x44, votes=weight=273, dims=12, w_records=273, records=2419, aisc_checked=12, aisc_mismatch=[], w_plausible_share=0.9964 |  |
| D3 Section field sanity | **NA** | policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - no structural members decoded (EC-08: wrong type offset) |
| D4 Work-line / roll field sanity | **NA** | policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - no structural members decoded (EC-08) |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=None, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=197, present=197, missing=0, unexpected=0, shared_recorded_once=8, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=189, manifest_solids=189 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[194.7, 113.3, 202.3], decoded_span_in=[194.7, 113.3, 202.4], span_ratio=[1, 1, 1], centre_shift_in=[0, 0, 0.1] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=187, median_ratio=0.9958, within_tol_share=1, tol=0.15, p05=0.995, p95=0.998, by_family=PIPE=[187, 0.996], not_compared=weighed as concrete=2 |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=189, touching_share=1, isolated=0 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=178, on_parent_share=0.9944, off_parent=1, off_parent_touching_other_member=1, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member | 1 pieces sit on another member of the connection (EC-44), accepted on touching other member evidence |
| G4 Duplicate solids | **FAIL** | duplicates=4, already_in_sds2_job=0, introduced_by_converter=4, share=0.02116, converter_examples=[#7 / PIPE 1 1/4 STD (piece 128, inst 1) = #9 / PIPE 1 1/4 STD (piece 128, inst 1), #7 / PIPE 1 1/4 STD (piece 208, inst 1) = #9 / PIPE 1 1/4 STD (piece 208, inst 1), #7 / PIPE 1 1/4 STD (piece 188, inst 1) = #9 / PIPE 1 1/4 STD (piece 188, inst 1), #7 / PIPE 1 1/4 STD (piece 153, inst 1) = #9 / PIPE 1 1/4 STD (piece 153, inst 1)], source_examples=[], policy=level=FAIL, cause=pipeline, verifier_status=FAIL, why=4 repeat solid(s) made by the converter (one SDS2 piece written twice) | 4 repeat solid(s) made by the converter (one SDS2 piece written twice); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies) |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=189, rebuilt=187, no_decoded_counterpart=2, within_0_1in=0.615, within_3in=1, over_12in=0, median_err_in=0.0159, p99_err_in=1.979 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
