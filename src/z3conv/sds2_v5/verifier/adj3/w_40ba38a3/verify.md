# SDS2 -> STEP verification: 401_CONGRESS_ST_GRIDS__JOB_40ba38_stage2.step

## Verdict: CORRECT


## Corpus tier: A (pending evidence)


Overall check status: PASS | evidence: mass | stage: piece | version 7.619 | solids 6

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.619, mem_idx_size=3411064, calibrated_slot=3404, slot_family=slot 3404, layout=slot=0xd4c, type=0xc4c, p1=0x112, p2=0x186, pt_fmt=>f8, sec=0x26e, sec_fmt=>h, roll=0x274, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - version 7.619 (slot 3404) not validated before; trust rests on M/E checks (EC-04) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=406, base=0x10e, byte_order=little, dims_at=0x1c, weight_at=0x44, votes=weight=273, dims=12, w_records=273, records=2419, aisc_checked=12, aisc_mismatch=[], w_plausible_share=0.9964 |  |
| D3 Section field sanity | **PASS** | structural=5, with_section_share=1, distinct_sections=5, top_section=[MC10x22, 1], top_share=0.2, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **PASS** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=1, beams_level_share=1 |  |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=0, section_source=index, piece_name_path=slot=1024, name_off=306, sample_hits=5/5, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - section index disagrees with the piece names (EC-47: index off by one / wrong field) |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=6, present=6, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=6, manifest_solids=6 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[717.9, 3129, 150.8], decoded_span_in=[717.9, 3129, 150.8], span_ratio=[1, 1, 1], centre_shift_in=[0, 0.2, 0] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=6, median_ratio=1.002, within_tol_share=1, tol=0.15, p05=1.001, p95=1.022, by_family=W=[5, 1.002], PL=[1, 1], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **NA** | solids=6, touching_share=0.6667, isolated=2, policy=level=NOTE, cause=pipeline, verifier_status=FAIL, why=audit only: connectivity false positives on steel-in-concrete models | NOTE (audit only: connectivity false positives on steel-in-concrete models); verifier: FAIL - many solids float free of the structure (EC-24 placement / EC-15 stray) |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=1, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0, converter_examples=[], source_examples=[], policy=level=PASS, cause=pipeline, verifier_status=PASS, why= |  |
| G5 Piece solids match decoded placement (independent rebuild) | **NA** | solids=6, rebuilt=6, no_decoded_counterpart=0, within_0_1in=0.8333, within_3in=0.8333, over_12in=0, median_err_in=0, p99_err_in=3.421 | NOTE (rebuilt from each piece's topology vertices: 1.0 within 3 in (the verifier's raw vertex records include non-geometry points, EC-45)); verifier: FAIL - STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error) |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
