# SDS2 -> STEP verification: 6eeedc27_stage2.step

## Verdict: CORRECT (with warnings)

- G4 WARN: 2 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)

## Corpus tier: A (pending evidence)


Overall check status: WARN | evidence: mass | stage: piece | version 7.243 | solids 164

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **NA** | jsetup_version=7.243, mem_idx_size=37415244, calibrated_slot=None, slot_family=None, layout=, decode_error=job has only 2 members in mem_idx - empty or placeholder job, policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - layout auto-calibration failed (EC-01/EC-06): cannot decode this job |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=510, base=0x100, byte_order=big, dims_at=0x1a, weight_at=0x42, votes=weight=300, dims=12, w_records=316, records=2051, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **NA** | policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - no structural members decoded (EC-08: wrong type offset) |
| D4 Work-line / roll field sanity | **NA** | policy=level=NOTE, cause=verifier, verifier_status=FAIL, why=member-decoder check; stage-2 geometry comes from piece placements | NOTE (member-decoder check; stage-2 geometry comes from piece placements); verifier: FAIL - no structural members decoded (EC-08) |
| D5 Stray members (spatial outliers) | **NA** |  | too few members |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=None, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=164, present=164, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=164, manifest_solids=164 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **NA** | file_unit=MM, span_in=[1205, 566.4, 590.2], decoded_span_in=[1, 1, 1], span_ratio=[1205, 566.4, 590.2], centre_shift_in=[1232, 825.3, 137.1] | no reference extent: no decoded piece boxes and no decoded members (adapter) |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=164, median_ratio=1, within_tol_share=1, tol=0.15, p05=1, p95=1, by_family=HSS=[164, 1], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **NA** | solids=164, touching_share=0.0732, isolated=152, policy=level=NOTE, cause=pipeline, verifier_status=FAIL, why=audit only: connectivity false positives on steel-in-concrete models | NOTE (audit only: connectivity false positives on steel-in-concrete models); verifier: FAIL - many solids float free of the structure (EC-24 placement / EC-15 stray) |
| G3 Connection pieces sit on their parent member | **NA** | pieces_checked=162, on_parent_share=0.0617, off_parent=152, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=0.0617, basis=touching other member, policy=level=NOTE, cause=pipeline, verifier_status=FAIL, why=audit only: connectivity false positives on steel-in-concrete models | NOTE (audit only: connectivity false positives on steel-in-concrete models); verifier: FAIL - pieces placed away from their member and not confirmed elsewhere (EC-25 M vs M.T / EC-26 hole block read as material) |
| G4 Duplicate solids | **WARN** | duplicates=2, already_in_sds2_job=2, introduced_by_converter=0, share=0.0122, converter_examples=[], source_examples=[MISC #1 / HSS6x6x1/4 (piece 4134, inst 1) = MISC #1 / HSS6x6x1/4 (piece 4134, inst 11) (listed by the converter as SDS2's own), MISC #2 / HSS6x6x1/4 (piece 4134, inst 1) = MISC #2 / HSS6x6x1/4 (piece 4134, inst 12) (listed by the converter as SDS2's own)], policy=level=WARN, cause=source, verifier_status=FAIL, why=2 identical solid(s) placed twice by SDS2's own data (kept as stored) | 2 identical solid(s) placed twice by SDS2's own data (kept as stored); verifier: FAIL - identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies) |
| G5 Piece solids match decoded placement (independent rebuild) | **NA** | solids=164, rebuilt=0, no_decoded_counterpart=164, within_0_1in=0, within_3in=0, over_12in=0, median_err_in=None, p99_err_in=None |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
