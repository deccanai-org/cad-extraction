# SDS2 -> STEP verification: Seasons52_Job_2d7f40_stage2.step

## Verdict: INCORRECT

- G5 FAIL: STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error)

## Corpus tier: EXCLUDED

- checks failed: G5

Overall check status: FAIL | evidence: mass | stage: piece | version 7.135 | solids 17

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.135, mem_idx_size=456208, calibrated_slot=1416, slot_family=slot 1416, layout=slot=0x588, type=0x4, p1=0x106, p2=0x138, pt_fmt=>f4, sec=0x170, sec_fmt=>h, roll=0x176, decode_error=None, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - version 7.135 (slot 1416) not validated before; trust rests on M/E checks (EC-04) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=178, base=0x4e, byte_order=big, dims_at=0x1a, weight_at=0x2e, votes=weight=300, dims=12, w_records=316, records=2052, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=5, with_section_share=1, distinct_sections=5, top_section=[W36x300, 1], top_share=0.2, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **NA** | zero_length_share=0.2, huge_coord_share=0, raw_roll_invalid_share=0.6, columns_vertical_share=0, beams_level_share=0.3333, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - work points look mis-decoded (EC-11 zero-length / EC-12 garbage coords / EC-13 columns not vertical) |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=index, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=17, present=17, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=17, manifest_solids=17 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[115.9, 269.4, 124.3], decoded_span_in=[115.9, 269.3, 124.3], span_ratio=[1, 1, 1], centre_shift_in=[0, 0, 0] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=17, median_ratio=0.9935, within_tol_share=1, tol=0.15, p05=0.924, p95=1.009, by_family=L=[7, 0.926], HSS=[5, 0.93], PL=[3, 1], BPL=[2, 1], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=17, touching_share=0.9412, isolated=1 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=9, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0, converter_examples=[], source_examples=[], policy=level=PASS, cause=pipeline, verifier_status=PASS, why= |  |
| G5 Piece solids match decoded placement (independent rebuild) | **FAIL** | solids=17, rebuilt=17, no_decoded_counterpart=0, within_0_1in=0.8235, within_3in=0.8235, over_12in=0, median_err_in=0, p99_err_in=5 | STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error) |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
