# SDS2 -> STEP verification: MASTER_job_98adc8_stage2.step

## Verdict: CORRECT


## Corpus tier: A (pending evidence)


Overall check status: PASS | evidence: mass | stage: piece | version 7.233 | solids 5

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **PASS** | jsetup_version=7.233, mem_idx_size=85052, calibrated_slot=2494, slot_family=7.2xx, layout=slot=0x9be, type=0x988, p1=0x112, p2=0x172, pt_fmt=>f8, sec=0x1d4, sec_fmt=>h, roll=0x1da, decode_error=None |  |
| D2 Shape table (job_mtrl) sanity | **NA** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=297, dims=12, w_records=301, records=1400, aisc_checked=12, aisc_mismatch=[], w_plausible_share=0.9868, policy=level=NOTE, cause=verifier, verifier_status=WARN, why=the verifier's own member-decoder check; stage-2 geometry comes from piece placements | NOTE (the verifier's own member-decoder check; stage-2 geometry comes from piece placements); verifier: WARN - could not confirm shape dims against AISC |
| D3 Section field sanity | **PASS** | structural=3, with_section_share=1, distinct_sections=3, top_section=[W36x300, 1], top_share=0.3333, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **PASS** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=1, beams_level_share=1 |  |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=index, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=5, present=5, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=5, manifest_solids=5 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **NA** | file_unit=MM, span_in=[306, 16.7, 1254], decoded_span_in=[300, 1, 1254], span_ratio=[1.02, 16.66, 1], centre_shift_in=[3, 0, 0], policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=extent differs from a degenerate or partial reference (planar frame / few rebuildable pieces), not a units error | NOTE (extent differs from a degenerate or partial reference (planar frame / few rebuildable pieces), not a units error); verifier: FAIL - model scale is off (EC-19: inches written as mm or similar) |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=5, median_ratio=0.9921, within_tol_share=1, tol=0.15, p05=0.986, p95=1.005, by_family=PIPE=[2, 0.995], PL=[2, 0.987], W=[1, 1.006], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **NA** | solids=5, touching_share=0.6, isolated=2, policy=level=NOTE, cause=pipeline, verifier_status=FAIL, why=audit only: connectivity false positives on steel-in-concrete models | NOTE (audit only: connectivity false positives on steel-in-concrete models); verifier: FAIL - many solids float free of the structure (EC-24 placement / EC-15 stray) |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=2, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **PASS** | duplicates=0, already_in_sds2_job=0, introduced_by_converter=0, share=0, converter_examples=[], source_examples=[], policy=level=PASS, cause=pipeline, verifier_status=PASS, why= |  |
| G5 Piece solids match decoded placement (independent rebuild) | **NA** | solids=5, rebuilt=0, no_decoded_counterpart=5, within_0_1in=0, within_3in=0, over_12in=0, median_err_in=None, p99_err_in=None |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
