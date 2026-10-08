# Parametric construction scripts and issue models (build123d)

This package is in the **partial** tier: its delivered STEP files (`model/step/*.step`) are good conversions with known
gaps - parts the conversion dropped, parts it approximated, parts to check. For every delivered STEP that has been
processed there is a folder here with

1. a plain Python script, `build_model.py`, that rebuilds the model headless, part by part, from **schedules** (tables
   of members, plates, bolts, welds, profiles, cuts and openings extracted from the model's source), and
2. a second script, `build_issues_model.py`, that rebuilds the same model with **every part coloured by what is known
   about it** and writes the colour-coded STEP files in `issues/`, so that anyone can see at a glance what the delivered
   STEP lacks or only approximates, and regenerate those files from this folder alone.

Nothing here changes the delivered files: `model/`, `drawings/`, `manifest.jsonl`, `project.json` and the rest of the
package are exactly as delivered. Everything this release adds is under `scripts/`, and `scripts_manifest.jsonl`
lists every one of those files with its size, sha256, model id, provenance and code version.

```
scripts/
  README.md                  this file
  requirements.txt           pinned Python packages (build123d 0.13.0 and the exact versions it was tested with)
  steelbuild.py              the construction library shared by all models
  issues_lib.py              the colouring / issue-model library shared by all models
  scripts_manifest.jsonl     every file under scripts/: path, bytes, sha256, model_id, source, code_version
  <model folder>/            one folder per processed model, named after its STEP file (each run of characters other
                             than letters, digits, '.', '_' and '-' replaced by one '_'; a short model id suffix where
                             two names would clash)
    build_model.py           rebuild the model from its schedules
    build_issues_model.py    rebuild it with every part coloured (see "Issue models")
    model_info.json          ids, delivered STEP, source, verdict, counts, schedule fingerprint, partial record, code versions
    schedules/               what the scripts build from (see "Schedules"), plus
      issues.json            every flagged part: id, name, colour, category, reason, source evidence (machine readable)
      missing_parts.json     the parts the conversion DROPPED, with the geometry the SOURCE records for them
    verification/            the checks (see "Verification")
    issues/
      <model>_ISSUES_highlighted.step   the whole model, every part coloured (written by build_issues_model.py)
      <model>_MISSING_parts_only.step   only the dropped parts (present when the conversion dropped any)
      WHERE_TO_LOOK.md                  plain-language guide for a reviewer: per colour what, where (landmarks and
                                        millimetre coordinates) and why, with counts and the legend
    source/
      provenance.json        where the source the schedules come from is, and how it was obtained / checked
      model.ifc              only for models delivered from a Tekla DB1 or an SDS/2 job: the IFC regenerated / emitted
                             from that source (see "Sources")
```

## Run

```
pip install -r requirements.txt            # Python 3.11 (3.10+)
cd "<model folder>"
python build_model.py                      # whole model -> rebuilt_model.step in this folder
python build_model.py --list               # schedule summary, nothing is built
python build_model.py --assembly 302B      # assembly mark(s); --assembly-id ID, --mark 100B, --role bolt, --parts ID1,ID2
python build_model.py --jobs 8             # in parallel; the STEP is the same as with --jobs 1

python build_issues_model.py               # issues/<model>_ISSUES_highlighted.step (+ _MISSING_parts_only.step)
python build_issues_model.py --from-delivered "../../model/step/<delivered file>.step"
                                           # colour the DELIVERED STEP instead of the rebuild (its geometry kept
                                           # byte for byte; only product names and colour styling are added)
python build_issues_model.py --list        # counts per colour, nothing is built
python build_issues_model.py --help        # every option
```

Both scripts run headless: no GUI, no CAD licence, no network, no AI and no randomness. The same schedules give the
same STEP files whatever the number of parallel jobs; this is tested per model (see "Verification").

## Issue models (colours)

`build_issues_model.py` writes one STEP product per part, labelled with a clear name (for example
`MISSING concrete slab 165.1 mm ...`, `APPROX ...`), and gives every part one colour:

| colour | meaning |
|---|---|
| GREY | ok: the part is in the delivered STEP and our rebuild of it matches the source |
| RED | the conversion DROPPED this part: it is not in the delivered STEP. It is built **only from geometry the source records** for it (for example a slab outline and thickness, a rebar axis and diameter, a profile and its axis), listed in `schedules/missing_parts.json`. Where the source does not record a size, a clearly labelled marker stands in its place - never an invented shape |
| ORANGE | the converter approximated the part (a stand-in or simplified shape in the delivered STEP) |
| YELLOW | to check: the delivered part and the source disagree, or the evidence is incomplete |
| PURPLE | the part is in the delivered STEP but our script does not yet rebuild it perfectly (see `verification/verification.csv`) |

`schedules/issues.json` lists every flagged part with its colour, category, reason and the source evidence;
`issues/WHERE_TO_LOOK.md` says the same in plain language for a reviewer without CAD tools.

## Sources

The schedules come from the model's source, which `source/provenance.json` names:

- **IFC models** (`step_source` ifc): the IFC the delivered STEP was converted from - `model/ifc/...` in this package,
  or in the add-on package named in `model_info.json` (`source.converted_from_package`). It is not copied here.
- **Tekla DB1 models** (`step_source` db1): the delivered STEP was written by our DB1 decoder through an intermediate IFC.
  That IFC is regenerated from `model/db1/...` with the decoder version that wrote the delivered STEP, its GlobalIds
  are restored from the delivered STEP, and the regenerated IFC is proven to reproduce the delivered STEP; it ships in
  `source/`. It is our decoder's own output, so the source check against it is a consistency check, not an independent
  reference.
- **SDS/2 models** (`step_source` sds2): the IFC emitted from the SDS/2 job with the pinned converter version that wrote
  the delivered STEP; it ships in `source/`, with the same caveat.

Nothing is invented: every dimension, position and cut comes from the source. Parts the source does not define as solids
(surfaces, open shells) are reported, not filled in.

## How a part is constructed

Every part is a set of solids. A **parametric** solid is a cross-section from `profiles.csv` (I, U, L, T, RECT, RHS,
CIRCLE, CHS, NGON, or a POLY outline from `profile_outlines.json`) placed on its plane (`solids.csv`), extruded along
its vector or swept along its path (`paths.json`), cut by its rows in `cuts.csv` (`plane`, `bounded_plane` with
`cut_boundaries.json`, `solid`) and finally reduced by its openings (`openings.csv`). Parts the source defines without
parameters are built from their polygon faces in `exact_geometry.jsonl`; `parts.csv` column `geometry` says which
construction applies (`parametric`, `recovered` - a faceted part rewritten as a parametric construction that coincides
with its facets - or `exact`).

## Schedules

| file | content |
|---|---|
| `parts.csv` | every part: id (IFC GlobalId), IFC class, role, name, profile, material, piece mark, assembly mark, assembly id, geometry kind, note |
| `members.csv`, `plates.csv`, `bolts.csv`, `welds.csv`, `assemblies.csv` | readable views (the build reads `parts`, `profiles`, `profile_outlines`, `solids`, `cuts`, `cut_boundaries`, `openings`, `paths`, `exact_geometry`; `--assembly` / `--assembly-id` also read `assemblies.csv`) |
| `profiles.csv`, `profile_outlines.json` | cross-sections |
| `solids.csv`, `cuts.csv`, `cut_boundaries.json`, `openings.csv`, `paths.json` | construction of every solid |
| `exact_geometry.jsonl` | polygon faces of the parts without parameters, and where they were read from (0 bytes when none) |
| `exact_sources.csv`, `part_properties.jsonl` | where faceted parts' faces came from; every property set the authoring tool exported |
| `issues.json`, `missing_parts.json` | the issue model's inputs (see "Issue models") |

All lengths are millimetres; positions are the source model's world coordinates (converted from feet where the source
was in feet).

## Verification

Per model, in `verification/` (a check whose pipeline step failed is absent; `model_info.json` `checks_absent` says which):

| file | what is checked |
|---|---|
| `verification.csv`, `verification_summary.json` | every rebuilt part: valid closed solids, compared with the delivered STEP (volume, centre, bounding box) and with the exact source geometry; `status = match` when both agree within the stated, absolute tolerances (never loosened) |
| `assemblies_verification.csv`, `assembly_marks_verification.csv`, `piece_marks_verification.csv`, `levels_summary.json` | every assembly, assembly mark and piece mark, and the whole model |
| `e2e_results.csv`, `e2e_summary.json` | `build_model.py` run exactly as a user runs it (whole model, a sample of `--assembly-id` and `--mark` runs), read back and checked part by part; row `determinism`: two runs with different `--jobs` give byte-identical STEP DATA sections |
| `tekla_*`, `reference_defects*`, `source_kernel_log.jsonl` | the authoring tool's own quantities against the rebuild; evidence for every part that does not match |
| `pmx_summary.json`, `step_times.tsv` | the pipeline run: verdict, step exit codes and times |
| `issues_e2e.json` | `build_issues_model.py` run from this folder: the default run whose files are in `issues/`, a second run (other `--jobs`) with byte-identical DATA sections, a `--from-delivered` run, `--list` counts against `issues.json` |

A model is **perfect** (`model_info.json` `verdict.perfect`) only when every pipeline step ran without error, every part
matches both references, no delivered part is left unbuilt, every assembly and mark is ok and every end-to-end run
passes; otherwise `verdict.reasons` lists what failed, and the parts concerned are PURPLE in the issue model.
