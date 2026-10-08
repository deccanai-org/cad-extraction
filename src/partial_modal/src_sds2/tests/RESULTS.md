# src_sds2 unit test: new sample n5 on Modal

Model `5d5b9446d811bd5f1a8d692e`: n5_sds2, package `Zenitude-data-3__Completed_Jobs_Data_Jobs From External Disk_Data
Room # Expansion_BACKUP_DATA ROOM_1021.7z`, `model/step/BACKUP_DATA ROOM_1021.step` (13,757,052 B, class M),
SDS/2 job `model/sds2/BACKUP_DATA ROOM_1021.zip` (92,704,782 B). We ran only this model. The original 5 samples were
never run on Modal.

Command: `.venv/bin/modal run src_sds2/modal_sds2.py --job-file <scratch>/job_n5.json --result-file <scratch>/result.json`.
The job comes from `tests/make_test_job.py`: 24 h GET URLs, kept in the session scratchpad and never in this folder.
Workspace navaneeth, app `pmp-src-sds2`, one container per run, image `im-PzuxRtcQRbmoCmrVztuPj8` (Azure us-west),
4 CPU / 16 GiB.

## Result (runs 5 and 6, 2026-10-08 04:4x UTC, current code)

| check | result |
|---|---|
| converter pin | v4 `sds2-step-pipeline-v4-candidate.zip` sha256 c5b65d27..., basis `r2_run`. The step_key is under `sds2-step-r2-20260929-01/`. The fleet result JSON names v5.5.0, but it describes a later re-run that was not shipped, so it is recorded in `checks` and not used |
| converter re-run | rc 0 in about 34 s. The STEP is byte-identical to the shipped STEP below FILE_NAME, and FILE_NAME matches with its time stamp blanked |
| IFC emit | 645/645 instances emitted, 164 unique parts, 0 unsupported, 0 hook errors |
| per-instance proof | reproduced: 645/645 matched. 0 only-in-STEP, 0 only-in-IFC, 0 failing, 0 name mismatches. Max deviation: vol_rel 1.8e-11, centroid 4.7e-9 mm, bbox 5.0e-9 mm. Tolerances: 1e-3 / 0.05 mm / 0.05 mm |
| facts | 645 instances: 300 exact, 142 sds2_bolt, 143 nominal_bolt, 55 turned_primitive (WS1/2 studs), 2 joist_envelope (18K3), 1 member_envelope (HSS5x5x1/4), 1 concrete_prism, 1 approximated (GR1 plate_fallback). 3 skipped pieces (fallback_over_5x_source_weight), and all 3 have confirmed geometry (see below). 0 members without geometry. 476 cut hole tools on 144 instances. errors [] |
| wall time | 68 s and 71 s per run (fetch about 15 s, convert about 34 s, proof about 20 s) |
| volume | `pmp-out:/5d5b9446d811bd5f1a8d692e/source/` with model.ifc, provenance.json, sds2_facts.json, reproduction.csv.gz and converter/. Logs are in `/logs/src_sds2.log` and `src_sds2_result.json` |

Determinism (sha256 of the outputs):

| run | model.ifc | sds2_facts.json | reproduction.csv.gz |
|---|---|---|---|
| 2 (before facts existed) | a2571fe933f710fc... | - | - |
| 3, 4 (facts v1) | a2571fe933f710fc... | a0a8346138b984f5... | 283b9f7345099cee... |
| 5, 6 (facts with skipped geometry) | a2571fe933f710fc... | de2b6c4e855497a5... | 283b9f7345099cee... |

The IFC is identical across all 5 runs. The facts and the reproduction table are identical between the runs that
used the same code.

## The 3 skipped gratings (RED parts)

The converter skipped 3 bar-grating panels: MISC #62 piece 521 `GR1 1/2x35 13/16`, and MISC #63 and #67 piece 523
`GR1 1/2x21 9/16`. The reason is that its plate fallback came out more than 5 x the SDS/2 weight. Its own weight
tally exempts `GT` gratings but not `GR` ones.

For each panel, the facts give a `prism_world` geometry. It is the hull of the piece's own vertex records: a clean
4-point rectangle of 236.46 x 35.8125 in or 236.46 x 21.5625 in, extruded 1.5 in = 38.1 mm. Two source records
confirm it:
- The name designation: depth 1 1/2 in and width 35 13/16 or 21 9/16 in, within 1/16 in.
- The member work line: 236.46 in, equal to the panel length.

The envelope weighs 3,602 or 2,169 lb, against 636 or 389 lb in the piece table. That ratio of about 5.6 is the open
mesh against the solid panel. Each `what` text says the bars are not modelled.

Negative checks of `facts_build.skipped_geometry` (run offline on these records):
- The same envelope under a mismatching name and weight is withheld: "not confirmed by the name, the piece table size
  or weight".
- A hull pushed far outside the model is withheld: "outside the model's parts box + 2 m".

## Run 7: the app's job schema

Run 7 used the jobs component's own n5 row from `jobs/urls/new5.signed.jsonl`: `pin`, `conv.step_key`, `step{}`,
`source{}` and `urls.source`, with no stage-specific keys. `stage.adapt_job` mapped it. The result was reproduced and
`pin.py agrees (basis r2_run)`. The IFC and the reproduction table were the same as in runs 5 and 6. The facts
differed from runs 5 and 6 only in their `converter` (pin) record: basis `job_pin:r2_v4` plus the jobs component's
evidence. The volume `/5d5b9446d811bd5f1a8d692e/source/` now holds the run 7 outputs: IFC a2571fe933f710fc...,
facts 46a69fbb282d50ad..., reproduction 283b9f7345099cee...

## Earlier runs

Run 1 was the image build plus the first run. Runs 2 to 4 used the code before the skipped-piece geometry was added.
All of them were reproduced with the same IFC sha256.
