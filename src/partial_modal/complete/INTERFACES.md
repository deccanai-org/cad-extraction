# Completion interfaces (pmp-completion, v1) - READ THIS BEFORE WRITING TRACK OUTPUT

Owner: track `integrate` (`complete/integrate/`, `app_v2/`). Every other track (`db1`, `sds2_ifc`, `standards`,
`estimate`) hands its work to the integration as ONE JSON file per sample:

```
complete/<track>/out/<tag>/patch.json          schema "pmp-completion-patch/1" (below); <tag> or its short form n1..n5
complete/<track>/out/<tag>/<anything else>     your evidence / logs (not read by the integration)
```

`<tag>` = `n1_db1_small` | `n2_db1_addon` | `n3_ifc_approx` | `n4_ifc_c2s` | `n5_sds2` (jobs/new5.jsonl).

Check a patch before handing it over (no CAD, seconds, fine on the Mac):

```bash
python3 complete/integrate/validate_patch.py complete/<track>/out/<tag>/patch.json      # schema + ids + provenance
python3 complete/integrate/merge.py --tag <tag> --dry-run                                # merge every track's patch, print counts
```

## 0. What you patch: the BASELINE scripts tree

The baseline (diagnostic) run wrote, per model, `scripts/<model_folder>/` = `build_model.py` + `schedules/` +
`verification/` + `issues` (colour-coded problems). Local copies (read-only, do not edit):

| tag | baseline tree (local) | Modal volume `pmp-out` |
|---|---|---|
| n1_db1_small | `testB_results/n1/scripts/51_Westwood_PETCT_Master/` | `/992c3de4.../scripts_tree/` |
| n2_db1_addon | `testB_results/n2/scripts/F232-MASTER-d6c7cd/` | `/4d188bba.../scripts_tree/` |
| n3_ifc_approx | none: the baseline pipeline FAILED (extract+exact); a track must supply schedules (see 6) | `/8314903e.../` |
| n4_ifc_c2s | `testB_results/n4/scripts/GRID3/` | `/701f5f69.../scripts_tree/` |
| n5_sds2 | `testB_results/n5/scripts/BACKUP_DATA_ROOM_1021/` | `/5d5b9446.../scripts_tree/` |

Useful baseline files: `schedules/parts.csv` (part ids = the ids you reference), `schedules/issues.json` (`parts[<id>]`:
colour, flags[{category, reason, evidence}], bbox, where), `schedules/missing_parts.json` (RED parts with ids `missing`
entries), `schedules/cuts.csv` / `openings.csv` / `solids.csv` (cut ids you may remove), `verification/verification.csv`.
Units: **mm, model world coordinates** (the schedules' own frame), everywhere in this document.

## 1. The six colours (one per part in the COMPLETED model)

| colour | label prefix in the STEP product name | meaning | who may emit it |
|---|---|---|---|
| GREY | (none) | original geometry, verified correct, unchanged | integration only (never in a patch) |
| GREEN | `GREEN-RESTORED` | restored EXACTLY from data in the source file (DB1 / SDS/2 / IFC) the conversion ignored or broke | `db1`, `sds2_ifc` |
| BLUE | `BLUE-STANDARD` | built from a cited industry standard table (ASTM/RCSC/ASME bolts, nuts, washers; AWS D1.1 studs; ASTM A615 rebar; AISC / Tekla-catalogue HSS radii; SJI joists; bar grating; anchor rods) | `standards` (others only with a `standard` citation) |
| AMBER | `AMBER-ESTIMATED` | no exact data and no standard: best inference (neighbours, repeated marks, symmetry, drawings / NC1 / KISS) | `estimate` (others only with a `basis`) |
| MAGENTA | `MAGENTA-NOT-EXACT` | our script's rebuild still differs from the target geometry | integration only (computed: build failed, invalid/open solid, target check failed, or a baseline problem nobody fixed) |
| RED | `RED-POSITION-ONLY` | nothing known beyond a position: a marker | any track (`marker` op); should be 0 |

One part, several ops: the part takes the WEAKEST colour: RED > MAGENTA > AMBER > BLUE > GREEN > GREY (e.g. GREEN
fitting cuts + an AMBER slot -> AMBER; the name lists every op). Untouched parts stay GREY only if the baseline
verified them (`verification.csv` status `match`) and no unresolved ORANGE/RED/PURPLE flag sits on them; otherwise the
integration colours them MAGENTA with the reason (honest record: "not fixed").

## 2. patch.json

```json
{
  "schema": "pmp-completion-patch/1",
  "track": "db1",                                   // db1 | sds2_ifc | standards | estimate
  "tag": "n1_db1_small",
  "model_id": "992c3de4...",                         // sha256 of the source = jobs/new5.jsonl model_id
  "generated_by": "complete/db1/make_patch.py",      // the script that wrote this file (re-runnable)
  "generated_at": "2026-10-07T23:10:00Z",
  "inputs": {"<file>": "<sha256>"},                  // what you read (source file, kit, tables)
  "ops": [ OP, OP, ... ],                            // applied in order; ids unique within the patch
  "notes": ["free text"]
}
```

### 2.1 Ops (every op: `op`, `id` (unique in the patch, stable across re-runs), `colour`, `provenance`)

| op | fields | effect |
|---|---|---|
| `add_part` | `part` (PART), `geometry` (GEOM) | a new part. Its part_id = `C` + 21 chars of sha1(`<track>:<id>`) (deterministic); give `part.part_id` yourself only if the source has one (e.g. an IFC GlobalId / Tekla GUID not yet in parts.csv) |
| `replace_part` | `part_id` (existing), `geometry` (GEOM), `part` (optional field overrides) | the part's old solids / cuts / openings / exact geometry are dropped and rebuilt from GEOM |
| `add_cuts` | `part_id` (existing), `cuts` [CUT], optional `solid_ids` (default: every body solid of the part) | cuts added to the part's existing body solids (fittings, line cuts, copes, holes) |
| `replace_cuts` | `part_id`, `remove_cut_ids` [cuts.csv cut_id], `remove_opening_ids` [openings.csv opening_id], `cuts` [CUT] | e.g. a round bolt hole replaced by its slot |
| `set_fields` | `part_id`, `fields` {name, part_mark, assembly_mark, material, ...} | metadata restored (colour stays as is unless you give `colour`) |
| `marker` | `part` (PART), `point` [x,y,z], optional `size` (default 100) | RED: a cube at the only thing known, a position |
| `accept` | `part_id`, `resolves` | a flagged baseline part reviewed and confirmed correct as it is (colour GREY, the note is recorded) |
| `remove_part` | `part_id` | only for a proven duplicate / phantom of the conversion; recorded in completion.json; use sparingly |

Common optional fields of every op:

* `resolves`: `[{"part_id": "<baseline id>", "category": "<issues.json flag category>"}]` - the baseline flags this op
  fixes (for `replace_part` / `add_cuts` / `replace_cuts` / `accept` the default is every flag of `part_id`). The
  integration uses it to decide which baseline problems are fixed; a baseline ORANGE / RED / PURPLE flag that no op
  resolves turns its part MAGENTA ("not fixed").
* `supersedes`: `["missing:<missing_parts.json id>"]` - your op replaces a RED entry the baseline drew from the source.
* `target`: `{"volume_mm3": v, "bbox": [x0,y0,z0,x1,y1,z1], "tol_rel": 0.005, "tol_mm": 0.5}` - the geometry you
  expect; the integration builds the part with the shipped script and colours it MAGENTA when the build differs.
* `where`: plain-language landmark ("level 2, column C6 at grid B-4") for CHANGES.md (the integration adds mm coords).

### 2.2 provenance (required; what CHANGES.md and the STEP product name say)

```json
{"what": "nut 3/4\" A563 DH heavy hex, 1 per bolt",            // plain language
 "source": "DB1 record 200148 bolt group: nut flag, diameter field (offset 0x44)",   // GREEN: file + record + field
 "standard": "ASME B18.2.6 Table 3: heavy hex nut 3/4: F=1.25 in, H=0.734 in",       // BLUE: standard + table + values
 "basis": "same mark B12 on 6 neighbours; symmetric about grid 4",                    // AMBER: why this estimate
 "evidence": {...}}                                              // anything machine readable
```

GREEN requires `source`; BLUE requires `standard`; AMBER requires `basis` (and should say "estimated"); RED requires
`source` or `basis` saying where the position comes from. The validator refuses a patch that breaks this.

### 2.3 PART (row of parts.csv; missing fields default to '')

`{"role": "member|plate|bolt|weld|accessory|concrete|other", "ifc_class": "IfcMechanicalFastener", "name": "NUT 3/4 A563",
"designation": "", "material": "", "part_mark": "", "assembly_mark": "", "drawing_ref": "", "assembly_id": ""}`

### 2.4 GEOM (one solid, or several with `compound`)

| kind | fields | built as |
|---|---|---|
| `profile_extrusion` | `profile` {profiles.csv row without profile_id: `kind` I/U/L/T/RECT/RHS/CIRCLE/CHS/NGON/POLY + its dims}, `outline` (POLY only: {"outer": [SEG], "inner": [[SEG]]}), `start`, `end`, `x_dir` (section x axis) | a straight member: section on the plane at `start` (z = start->end, x = x_dir), extruded to `end` |
| `cylinder` | `start`, `end`, `radius` | round bar / shank / anchor rod / stud |
| `hex_prism` | `base_center`, `axis` (unit, height direction), `height`, `across_flats`, optional `x_dir` (a flat's normal), optional `hole_diameter` | nut / bolt head |
| `ring` | `base_center`, `axis`, `height`, `outer_diameter`, `inner_diameter` | round washer |
| `prism` | `outline_world` [[x,y,z], ...] (planar polygon, any order, closed implicitly), `normal`, `thickness`, optional `offset` (default 0: the outline is one face, the solid goes `thickness` along `normal`) | plate, slab, wall, grout, concrete |
| `sweep` | `profile` (+`outline`), `points` [[x,y,z],...] (polyline path), `x_dir` | bent bar / polybeam with joints (steelbuild paths.json) |
| `faceted` | `solids` [{"faces": [[outer_loop, hole_loop...], ...]}] (loops = [[x,y,z],...]) | exact polyhedral solid (steelbuild exact_geometry) |
| `schedule_part` | `schedules` (dir), `part_id` | that part's rows from another schedules folder (section 7) - a whole part, not inside a compound |
| `box` | `origin`, `x_dir`, `y_dir`, `size` [dx,dy,dz] | block |
| `compound` | `items` [GEOM, ...] | several solids of one part (bolt = head + shank + nut + washers) |

SEG (profile outlines, 2D in the section plane): `{"t": "L", "p": [[x,y], [x,y], ...]}` polyline, `{"t": "A", "p":
[start, mid, end]}` circular arc (as steelbuild `profile_outlines.json`).

Every GEOM except `faceted` may carry `cuts: [CUT]` (applied to that solid only).

### 2.5 CUT

| kind | fields | removes |
|---|---|---|
| `plane` | `point`, `normal` | everything on the side OPPOSITE to `normal` (the part keeps the side `normal` points to) |
| `solid` | `tool` (GEOM, one solid) | the tool's volume (hole = `cylinder`, slot = `prism` with a stadium outline or `profile_extrusion` POLY with arcs, cope = `box` / `prism`) |

Slots: do NOT use a RECT profile with r_outer = b/2 (the IfcOpenShell kernel rule in steelbuild drops such tools for
parametric parts); use `prism` / POLY with `A` arcs.

## 3. What the integration does (`complete/integrate/merge.py`, Modal stage `complete` in `app_v2/`)

1. baseline schedules -> `schedules_original/` (unchanged; the baseline `build_issues_model.py` reads it);
2. every `complete/*/out/<tag>/patch.json` validated, then applied in the order db1, sds2_ifc, standards, estimate
   (a later op on the same part composes: cuts add up, a later `replace_part` wins and both are recorded);
3. baseline `missing_parts.json` entries with real geometry (prism / cylinder / profile / schedule_part) not
   superseded -> added GREEN (geometry from the source record); marker-only entries -> RED;
4. GEOM / CUT -> schedule rows (profiles.csv, profile_outlines.json, solids.csv, cuts.csv, paths.json,
   exact_geometry.jsonl); new ids are namespaced (`P_<hash>`, `S_<hash>`, `C_<hash>`) so they never collide;
5. writes `schedules/` (COMPLETED) + `schedules/completion.json` (schema `pmp-completion/1`: colour, status, ops,
   provenance per changed part; counts; unresolved flags; inputs with sha256);
6. builds (Modal): `completed/<model>_COMPLETED.step` (coloured, one folder per colour, product names =
   `<PREFIX> <what> [<source|standard|basis>] | <part id> <name>`), `completed/<model>_COMPLETED_plain.step` (same
   solids, no colours, = `build_model.py` output), `completed/CHANGES.md`, `completed/verification.json`;
7. checks: every part a valid closed solid (else MAGENTA), untouched parts identical to the baseline rebuild (schedule
   rows equal AND volume/bbox equal), two builds byte-identical, read-back counts per colour.

## 4. completion.json (output, for readers)

```json
{"schema": "pmp-completion/1", "model_id": "...", "model_name": "...", "tag": "...",
 "colours": {"GREY": [0.78,0.78,0.78], "GREEN": [...], ...}, "meaning": {"GREEN": "..."},
 "counts": {"GREY": 0, "GREEN": 0, "BLUE": 0, "AMBER": 0, "MAGENTA": 0, "RED": 0},
 "parts": {"<part_id>": {"colour": "GREEN", "status": "added|replaced|modified|restored|marker|accepted|not_fixed|unchanged",
                         "name": "...", "label": "<STEP product name>", "ops": ["db1:fit:200148"],
                         "provenance": [{...}], "resolves": [...], "bbox": [...], "where": "..."}},
 "removed": [...], "unresolved": [{"part_id", "category", "reason"}], "inputs": {"<patch path>": "<sha256>"}}
```

Only parts that are not plain GREY are listed in `parts` (a GREY part = unchanged + verified).

## 5. Shipped files per model (published to `scripts/<model_folder>/`)

`build_model.py` (builds the COMPLETED model from `schedules/`), `build_completed_coloured.py` (the coloured +
plain COMPLETED STEPs), `schedules/` (completed, + `completion.json`), `schedules_original/` (baseline), `completed/`
(`<model>_COMPLETED.step`, `<model>_COMPLETED_plain.step`, `CHANGES.md`, `verification.json`), plus the baseline
`build_issues_model.py` / `issues/` (reads `schedules_original/`).

## 7. Form B: a completed SOURCE (IFC) instead of a patch (db1 / sds2_ifc tracks)

A track that re-decodes / re-emits the source with the restorations switched on hands over the completed IFC:

```
complete/<track>/out/<tag>/model_completed.ifc      products keep the delivered GlobalIds (new products: deterministic ids)
complete/<track>/out/<tag>/restoration_log.json     {"schema": "...restoration_log/1", "parts": {"<GlobalId>":
                                                      {"geometry": "restored" | "unchanged" | "CHANGED_WITHOUT_EVENT",
                                                       "record": ..., "events": [{"kind": "slotted_hole" | "fitting_applied"
                                                       | "<any>", "what": "...", "field": "DB1 ... field", ...}]},
                                                      "comparison_completed_vs_source_ifc": {"new_in_completed": ...}}
```

(= what `complete/db1/complete_core.py` already writes.) The integration then (Modal, `app_v2` stage
`complete_source`): runs the baseline pipeline's extract+exact / props / recover / verify on `model_completed.ifc`
(same code variant, same delivered STEP) -> completed schedules -> per part, canonical rows compared with the
baseline schedules: equal -> untouched (baseline rows kept, byte-identical); different -> `replace_part` GREEN with
`geometry: {"kind": "schedule_part", "schedules": "<dir>", "part_id": ...}` and the provenance from the log's events
(source = the event's `field` / `record`); new parts -> `add_part` GREEN; a change without an event -> MAGENTA
("changed without a restoration event"). That generated patch is written to
`complete/integrate/out/<tag>/patch_from_<track>.json` and merged like any other patch (other tracks' patches can
still reference baseline part ids; ops on the same part compose).

GEOM kind `schedule_part` (also usable in a hand-written patch): `{"kind": "schedule_part", "schedules": "<dir
with parts.csv/solids.csv/...>", "part_id": "<id there>"}` = that part's rows (solids, cuts + tool solids,
openings, profiles, outlines, cut boundaries, paths, exact record) copied with namespaced ids.

## 6. n3 (no baseline schedules)

The n3 baseline pipeline failed before writing schedules. Whoever fixes it hands the integration a full scripts
tree instead of a patch: `complete/<track>/out/n3_ifc_approx/scripts_tree/<model_folder>/schedules/...` (+ its
`verification/verification.csv` if it has one). The integration then treats that tree as the baseline.
