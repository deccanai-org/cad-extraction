# SDS2 -> STEP verification: SAMPLE_JOB_8d3cfa_stage2.step

## Verdict: INCORRECT

- D1 WARN: version 7.132 (slot 1416) not validated before; trust rests on M/E checks (EC-04)
- D4 WARN: some work points / rolls implausible (EC-11/EC-14)
- D5 WARN: members far from the building (EC-15: scratch/stray members kept in the job)
- G4 FAIL: identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)

## Corpus tier: A (confirmed (internal checks))

- 17 guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)
- 3 exact duplicate solids written by the converter: ship the de-duplicated copy (--dedup-out), not the original (G4)

Overall check status: FAIL | evidence: mass | stage: piece | version 7.132 | solids 230

Ground truth found: IFC 0, KISS 0, NC1 0

| check | status | key metrics | reason |
|---|---|---|---|
| D1 Version / layout gate | **WARN** | jsetup_version=7.132, mem_idx_size=1453072, calibrated_slot=1416, slot_family=slot 1416, layout=slot=0x588, type=0x4, p1=0x10a, p2=0x13c, pt_fmt=>f4, sec=0x1b2, sec_fmt=>h, roll=0x27a, decode_error=None | version 7.132 (slot 1416) not validated before; trust rests on M/E checks (EC-04) |
| D2 Shape table (job_mtrl) sanity | **PASS** | layout=record=178, base=0x4e, byte_order=big, dims_at=0x1a, weight_at=0x2e, votes=weight=300, dims=12, w_records=316, records=2052, aisc_checked=12, aisc_mismatch=[], w_plausible_share=1 |  |
| D3 Section field sanity | **PASS** | structural=47, with_section_share=1, distinct_sections=29, top_section=[W14x370, 9], top_share=0.1915, beam_family_ok=1 |  |
| D4 Work-line / roll field sanity | **WARN** | zero_length_share=0, huge_coord_share=0, raw_roll_invalid_share=0, columns_vertical_share=0.7727, beams_level_share=0.8333 | some work points / rolls implausible (EC-11/EC-14) |
| D5 Stray members (spatial outliers) | **WARN** | members=47, outliers=2, outlier_share=0.0426, threshold_in=4976 | members far from the building (EC-15: scratch/stray members kept in the job) |
| D6 Section index vs main-piece name | **NA** | agreement=None, section_source=index, piece_name_path=None | piece-name path not available for this job |
| C1 Completeness vs the SDS2 job (independent) | **PASS** | expected_pieces=230, present=230, missing=0, unexpected=0, shared_recorded_once=0, approximate_solids=0, member_envelopes=0, missing_by_kind= |  |
| S1 Solid count vs manifest | **PASS** | step_solids=230, manifest_solids=230 |  |
| S2 B-rep validity | **PASS** | valid_share=1, closed_share=1, positive_volume_share=1, single_solid_share=1 |  |
| S3 Solid names parse and are unique | **PASS** | parsed_share=1, duplicate_names=0, repeated_instance_names=0 |  |
| S4 Units and model extent | **PASS** | file_unit=MM, span_in=[2644, 725.9, 8804], decoded_span_in=[2644, 725.9, 8804], span_ratio=[1, 1, 1], centre_shift_in=[0, 0, 0] |  |
| M1 Mass vs SDS2 recorded weight (rolled/plate steel) | **PASS** | compared=230, median_ratio=1, within_tol_share=1, tol=0.15, p05=0.933, p95=1.04, by_family=PL=[77, 0.951], L=[62, 1.013], W=[44, 1.039], BPL=[29, 1], MC=[8, 1.003], C=[4, 1.01], HSS=[2, 0.993], PIPE=[2, 0.994], not_compared= |  |
| M2 Open-web joists represented plausibly | **NA** |  | no joists in this model |
| G1 Solid vs work line (length, top-of-steel, column axis) | **NA** |  | stage-2 pieces are cut to fabricated length; see E-checks |
| G2 Connectivity (solids touch neighbours) | **PASS** | solids=230, touching_share=0.9217, isolated=18 |  |
| G3 Connection pieces sit on their parent member | **PASS** | pieces_checked=160, on_parent_share=1, off_parent=0, off_parent_touching_other_member=0, off_parent_confirmed_by_ifc=None, resolved_share=1, basis=touching other member |  |
| G4 Duplicate solids | **FAIL** | duplicates=3, already_in_sds2_job=0, introduced_by_converter=3, share=0.01304 | identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies) |
| G5 Piece solids match decoded placement (independent rebuild) | **PASS** | solids=230, rebuilt=230, no_decoded_counterpart=0, within_0_1in=0.9565, within_3in=0.9565, over_12in=1, median_err_in=0, p99_err_in=6.51 |  |
| E1 SDS2 IFC export (aligned bbox IoU) | **NA** |  | no IFC for this job |
| E2 KISS bill of materials | **NA** |  | no KISS file |
| E3 DSTV NC1 parts | **NA** |  | no NC1 files |
