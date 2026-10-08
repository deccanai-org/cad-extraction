# SDS2 -> STEP verification: TEST2_JOB_d0bc23_stage2.step

## Verdict: CORRECT


## Corpus tier: A (pending evidence)


Overall check status: PASS | evidence: internal | stage: piece | version 8.004 | solids 3

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=8.004, mem_idx_size=3607456, calibrated_slot=3600, slot_family=slot 3600, layout=slot=0xe10, type=0xd0c, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x200, sec_fmt=<h, roll=0x206, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - version 8.004 (slot 3600) not validated before; trust rests on M/E checks (EC-04) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=446, base=0xbc, byte_order=little, dims_at=0x1c, weight_at=0x44, votes=weight=283, dims=12, w_records=283, records=2250, aisc_checked=12, aisc_mismatch=[], w_plausible_share=0.9965 |  |
| D3 Section field sanity | **PASS** | structural=3, with_section_share=1, distinct_sections=3, top_section=[L4x3x5/16, 1], top_share=0.3333, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **NA** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=1, columns_vertical_share=1, beams_level_share=1, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=index, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=3, present=3, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=3, manifest_solids=3 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **NA** | file_unit=MM, span_in=[14.5, 24, 4.1], decoded_span_in=[10.3, 24, 1], span_ratio=[1.403, 1, 4.06], centre_shift_in=[2.1, 0, 0], policy=level=NOTE, cause=verifier, verifier_status=WARN, why=extent differs from a degenerate or partial reference (planar frame / few rebuildable pieces), not a units error | NOTE (extent differs from a degenerate or partial reference (planar frame / few rebuildable pieces), not a units error); verifier: WARN - model extent differs from the decoded work points |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **NA** | all_parts=status=NA, reason=no recorded weights to compare, families_off=None, within_tol_share=None, compared=None, policy=level=NA, cause=pipeline, verifier_status=NA, why=judged on the parts claimed exact | no recorded weights to compare |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **NA** |  |  |
| G3 Connection pieces sit on their parent member | **NA** |  |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0, converter_examples=[], source_examples=[], policy=level=PASS, cause=pipeline, verifier_status=PASS, why= |  |
| G5 Piece solids match decoded placement (independent rebuild) | **NA** | solids=3, rebuilt=3, no_decoded_counterpart=0, within_0_1in=0.3333, within_3in=0.3333, over_12in=0, median_err_in=3.08, p99_err_in=3.08 | NOTE (rebuilt from each piece's topology vertices: 1.0 within 3 in (the verifier's raw vertex records include non-geometry points, EC-45)); verifier: FAIL - STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error) |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
