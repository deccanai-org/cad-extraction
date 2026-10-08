# complete/sds2_ifc - GREEN restoration track (SDS/2 + IFC models)

Restores, from the model's OWN source only, parts the conversion ignored or broke. Nothing estimated, nothing from
standards: anything that needs either is listed in `not_restored[]` with its handoff colour (AMBER / BLUE) and the exact
values the source does hold. Compute runs on Modal (app `pmp-complete-sds2ifc`, volume `pmp-out`,
`/<model_id>/complete/sds2_ifc/`); inputs come through the pre-signed GET URLs of `jobs/urls/new5.signed.jsonl`.

```
cd /Users/dhiren/Downloads/Deccan/partial_modal
# SDS/2 only: re-convert the job with a newer pinned converter build + read-only probe (bolt records, gratings, holes)
.venv/bin/modal run complete/sds2_ifc/modal_restore.py::probe --tag n5_sds2 --labels v5.5.11
# restorations (n3 / n4 IFC, n5 SDS/2) -> volume + returned summaries
.venv/bin/modal run complete/sds2_ifc/modal_restore.py::restore --tags n3_ifc_approx,n4_ifc_c2s,n5_sds2 --out res.json
# check every restored row with the shipped kit's own exact builder (steelbuild.exact_part = what build_model.py runs)
.venv/bin/modal run complete/sds2_ifc/modal_restore.py::diag --tag n4_ifc_c2s --script verify_rows.py \
    --args "{V}/complete/sds2_ifc/restored_geometry.jsonl {V}/complete/sds2_ifc/restoration_log.json" --keys step
```

| file | what |
|---|---|
| `restore_ifc.py` | IFC: open faceted shells closed from their own planar free loops (gate: closed + valid in OCC and in `steelbuild.exact_part` + volume = the IFC's own Qto / analytic volume within 1e-4); >5 % volume parts (boolean collapse / first-operand fallback) detected; products missing from the STEP diagnosed |
| `restore_sds2.py` | SDS/2: parts the newest converter build makes from the job's own records with no stand-in tag (gratings), guessed bolts that duplicate SDS/2's stored bolt pieces (removed), audits of bolt records / anchors / members without pieces / mating holes |
| `sds2_probe.py` | runs one pinned converter build on the job (converter env) and dumps every SDS/2 bolt record (main + header frames), pieces, members |
| `verify_rows.py` | builds every restored row with `ref/steelbuild.py` (copy of the shipped kit) and checks validity + volume |
| `diag_closure.py` | diagnostics of one open body (closure variants, per-face validity) |
| `modal_restore.py` | the Modal app (images = `src_sds2` image: /opt/conv converter env + /opt/pipe pipeline env) |
| `out/<tag>/` | local copy of the outputs |

## Outputs per model (`out/<tag>/`, same on the volume)

* `restoration_log.json` (`pmp-restoration-log/1`): `entries[]` (GREEN parts: part_id, kind, what, source_fields, basis,
  checks), `removed[]` (delivered parts to drop, with the stored part that replaces them), `not_restored[]` (with `why`
  and `handoff`), `checked{}` (what was audited and the counts), `inputs` (sha256 of every input), `outputs` (sha256).
* `restored_geometry.jsonl`: one row per GREEN part in the schedules' `exact_geometry.jsonl` format
  (`part_id`, `source`, `solids[{faces[[outer],[holes]...]}]`, world mm) + `restore{colour, kind, replaces}`.
  Deterministic: byte-identical across runs (checked twice on Modal).
* `restored_green.step`: preview of the GREEN parts only (green, provenance in the product names). Not byte-stable
  across runs (OpenCASCADE entity order); the build uses the jsonl rows, not this file.
* n5 also: `brep/*.brep` (the grating solids as built), `probe_v5.5.11/` (manifest, pieces table, probe.json).

## Integration contract (for the assembler)

* IFC (n4): the 6 rows replace the parts' `delivered_step` source: put the row into `exact_geometry.jsonl`, set
  `parts.csv geometry=exact`, `exact_sources.csv` = "IFC faceted geometry; open shell closed from its own planar free
  loops (GREEN)". Colour GREEN, provenance from the log entry.
* SDS/2 (n5): `part_id` of a grating row is `sds2:<member>:<piece>:<inst>`; the delivered GR1 piece 520 instance (a
  solid panel) is REPLACED (`restore.replaces` names its delivered label); pieces 521 / 523 x2 were missing. The 65
  `removed[]` nominal bolts are dropped from the completed model (their stored BLT pieces stay GREY).

## Results (2026-10-08, Modal)

| sample | GREEN | removed | not restored (handoff) |
|---|---|---|---|
| n3 IFC 31-2214 GCP3_STL | 0 | 0 | 6 bolt assemblies (12 bolts) missing from the STEP: every MappingTarget.LocalOrigin references `#0` (dangling) and both bodies of each group share that one operator, so the bolt positions are not in the file -> AMBER (shape, count, A325N 3/4" x 4", hole 20.6, washers / nuts, group placement are exact and listed) |
| n4 IFC GRID3 | 6 plates PL1/4"X5 9/16" (open shells closed; volume = IFC Qto 1,005,872 mm3, rel dev 2e-8; valid in OCC and in the kit) | 0 | 0 |
| n5 SDS/2 BACKUP_DATA ROOM_1021 | 4 bar gratings GR1 (piece 520 panel replaced, 521 + 523 x2 missing) built from SDS/2's grating record + piece faces, weight 1.0001 x SDS/2 | 65 guessed 3/8" bolts on SDS/2's own stored BLT bolts | 78 guessed bolts with no record (BLUE), 15 bolt-crossing holes with no diameter (BLUE), 104 single-ply holes (none), BEAM #8 HSS5x5x1/4 with no pieces (AMBER) |

Audited and found nothing to restore: n3 / n4 volume vs IFC (max 0.06 % / 0.17 %, 0 over 5 %: no boolean collapse or
first-operand fallback); n5 SDS/2 bolt records (142 f64 records, all already bolts in the delivered model, 0 unused);
n5 expansion anchors (no anchor records in the job, no bolt reports in the package); n5 members without geometry (0).
