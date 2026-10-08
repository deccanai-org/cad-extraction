# issues/ - colour-coded issue models (pmp component)

What it makes, per model, inside `scripts/<model_folder>/` of the package:

| file | made by | what |
|---|---|---|
| `schedules/issues.json` | `make_issues.py` (pipeline, on Modal) | every flagged part: id, name, colour, every flag (category, reason, evidence), where it is (landmarks + mm box); counts per colour for both modes; the partial record reconciled row by row (every difference explained); the checks made / not made and why; sha256 of every input |
| `schedules/missing_parts.json` | `make_issues.py` | every RED part with the geometry its SOURCE records (schedule part = the source IFC product built by steelbuild; DB1 outline + thickness; rod axis + diameter; bolt shanks over the recorded grip; SDS/2 vertex envelope confirmed by src_sds2) or a clearly labelled MARKER (recorded position / extent, size or shape unknown). Never invented geometry |
| `issues/WHERE_TO_LOOK.md` | `make_issues.py` | plain language for a non-CAD reviewer: legend, counts, landmarks (levels, nearest column, model edges, mm), per colour what / where / why, the record reconciliation, what was checked |
| `issues/<model>_ISSUES_highlighted.step` | **the shipped `build_issues_model.py`** (run from the scripts/ tree) | the model rebuilt from the schedules (the same solids as `build_model.py`), every part coloured, one folder per colour |
| `issues/<model>_MISSING_parts_only.step` | the shipped `build_issues_model.py` | only the RED parts (written only when something is missing) |

Colours: GREY fine, RED missing (dropped by the conversion), ORANGE approximated by the converter, YELLOW to check,
PURPLE our build123d script not perfect yet. One colour per part, precedence RED > YELLOW > ORANGE > PURPLE (as the
hand-made sample overlays); the part's STEP name starts with MISSING / CHECK / APPROX / OUR-SCRIPT-NOT-PERFECT and
lists every reason.

## Files here

| file | shipped? | role |
|---|---|---|
| `issues_lib.py` | yes, `scripts/issues_lib.py` (shared) | STEP text reader / editor (delivered mode), geometry of RED parts, coloured export, XCAF read-back |
| `build_issues_model.py` | yes, `scripts/<model>/build_issues_model.py` | the user-facing script (see its `--help`) |
| `make_issues.py` | no (pipeline) | the issue maker: partial record + conversion detail + source side tables + our verification -> issues.json, missing_parts.json, WHERE_TO_LOOK.md |
| `stage.py` | no (pipeline) | the app's plug-in entry `run(job, ctx)`: downloads the conversion detail files, runs make_issues.py |
| `tests/modal_unit.py` | no | unit test on Modal (new samples only) |

## The shipped script

```
cd scripts/<model_folder>
python build_issues_model.py                  # rebuild mode -> issues/<model>_ISSUES_highlighted.step (+ MISSING file)
python build_issues_model.py --from-delivered # the delivered STEP (../../model/step/...) coloured as text: only names change,
                                              #   colour styling appended, geometry statements byte for byte (checked
                                              #   after writing) -> issues/<model>_ISSUES_on_delivered.step
python build_issues_model.py --list           # counts per colour + categories, nothing built
python build_issues_model.py --verify         # also read the files back with OpenCASCADE XCAF (names + colours)
python build_issues_model.py --jobs 8         # parallel build (same bytes as --jobs 1)
```
Headless, deterministic (the STEP header time stamp is the delivered STEP's own; same inputs -> byte-identical files),
exit status 1 when any count differs from issues.json, a check fails or a part that should be drawn is not.

## Rules (what makes which colour)

| colour | category | evidence |
|---|---|---|
| RED | dropped_by_conversion | schedule (source) part id not among the delivered part ids (IFC GlobalId; SDS/2: sds2label id) |
| RED | skipped_by_converter | DB1 record the converter skipped (src_db1 skipped_records.json, only when `usable_for_red_parts`) |
| RED | not_built_by_converter / member_not_written | SDS/2 piece / member the converter did not write (src_sds2 sds2_facts.json) |
| ORANGE | surface_model / partial_surface / alt_source / triangulated | converter part log (`*.parts.json`) fallback levels L4..L1 |
| ORANGE | volume_off | converter join check, > 5 % off the source volume |
| ORANGE | fitting_not_applied, slotted_holes_round, slotted_ply_round_holes, cut_not_applied, bolt_nominal_head_nut, washer_nominal, ... | `[approx: ...]` tags in the delivered names + src_db1 skipped_records.json (fittings, slotted groups and their plies, unbuilt cut bodies) |
| ORANGE | bolt_from_hole_stack, joist_envelope, joist_standin, member_envelope, concrete_prism, plate_fallback, grating_solid_panel, piece_approx | SDS/2: src_sds2 facts category per instance, delivered labels, the converter's piece table |
| YELLOW | open_in_source, sewn_by_converter, stray_faces, open_surface, opening_repaired, unverified, ... | converter part log tags |
| YELLOW | duplicate, duplicate_id, split_in_pieces, invalid_delivered, stray_part, derived_hole | converter read-back check / step_parts / part log / labels |
| PURPLE | our_script_* | our verification.csv (MISMATCH, INVALID_SOLID, BUILD_ERROR, BUILD_CRASH; rebuild of a missing part differing from the source) |
| PURPLE | delivered_part_not_in_schedules | a delivered part our schedules lack |

Not coloured, noted: `approx-curved` (curved faces stored as facets: the faceted-STEP format, not a part defect).

## Test

```
cd /Users/dhiren/Downloads/Deccan/partial_modal
.venv/bin/modal run issues/tests/modal_unit.py                 # n1_db1_small + n5_sds2 (new samples only)
```
Results: `/vol/_unit/issues/<id>/unit/` and `issues/tests/results/<tag>/` (result.json: checks, counts, the record
reconciliation, run logs).
