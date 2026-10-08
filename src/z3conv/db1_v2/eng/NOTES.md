# db1 v2 — engine variants + fittings (eng fork)

All patches are drop-in copies of the kit files; nothing in `z3conv/db1/` was edited.

| file | what |
|---|---|
| `src/db1dec.py` | decoder: record-variant retry (spread / geo / flag1) + float64 contour outlines (9.08 / 9.50) |
| `handoff_v2/` | **shipped to the builder**: db1dec.py, db1step.py (= builder's 17:18 db1step + `patch_db1step.py`), attrlink.py, diffs |
| `src/layouts.json` | + 9.21 and 9.50 entries (shipped to the builder as `handoff_9x/layouts.json`, deployed as code z3-db1-2026-10-01j) |
| `step/db1step.py`, `step/db1step.patch` | writer (diff vs the builder's db1step.py of 2026-10-01 16:2x): fittings + line cuts, attr-link overrule, empty-model statuses |
| `fittings.py` | Tekla fittings (relation type 9) and line cuts (type 12) decoder + writer helpers |
| `attrlink.py` | naming-independent evidence for the part -> attribute link |
| `guid2.py`, `validate.py`, `memdetail.py`, `planeval.py`, `cutval.py`, `e2e_fit.py`, `fitval.py` | ground-truth tools (Tekla IFC joined by GUID) |
| `box/` | job driver for BOX-B (not run: see "blocked") |

## 1. Decoder: record variants (`db1dec.py`)

data-4 `no_member_layout` (193 jobs) has the same field layout as the working models. Three record variants make the
table-detection gates reject the tables:

| variant | what goes wrong today | example |
|---|---|---|
| spread | the part-csys run (stride 61) opens with ~40 non-orthogonal pairs (dot 0.0045); the gate samples only the first 48 records | 8.85 HARRAHS CASINO 4faa624772 |
| geo | points at georeferenced coordinates (x 2.0e8, y 2.3e8 mm) fail the 1e8 mm plausibility bound | 8.85 2611-CBMAA family (~70 jobs) |
| flag1 | live records carry header flag 0x01 (or 0x05) instead of 0x04, so `segment()` never sees most tables | 8.07 22-005 MOB 31b6405d38: 8,781 of 9,321 parts flag 1 |

Change: `decode()` retries the known layouts with these variants (`RETRY`, `_variant_retry`) **only after the normal fast and
semi paths found nothing** (before full discovery). Acceptance = existing `_accept` + axis agreement >= 0.9 + unique part
seqs. `Db.SEG_FLAGS`, `Db.CSYS_SPREAD`, `Db.PLAUS_MAX` default to today's behaviour. The returned layout carries `variant`.

Validation:
* 4faa624772 (8.85, spread): 1,781 members, 1,780 profiles, axis 1.0 (was no_member_layout; full discovery had run 28 min and failed).
* ea6e61a05a (8.85, geo): 32,788 members, axis 1.0 (the folder's IFC has no extruded bodies, so no per-part truth yet).
* 31b6405d38 (8.07, flag1), vs its Tekla IFC (GUID join, 5,148 joined): contour plates 1,242/1,242 exact (centroid <= 1 mm,
  area <= 1 %); members: profile 879/879, axis collinear 97.8 %; ends differ only on parts the IFC cuts (fittings, see 3).
* Regression before/after (identical members, geometry, plates, layout): 7.64 ag_606ed3d8, 8.07 s807 (HDK), 7.82 4f7fa9df65,
  9.08 3089c30191. 8.85 / 8.53 / 8.44 / 7.64-nml were stopped when the Mac was put off-limits -> to run on BOX-B.

Family coverage of the 193 NML + 43 suspect (data-4): 2611-CBMAA 77 (geo), ATLANTIC PARK 42, 3602_MTSU 26 + MTSU academic 8
(8.07), 0683-QCPS 21 (8.85), 31519 Concourse 43 (suspect_attr_link), Dry Dock 4, Intel CUB2 9.08 3 (291 MB), others 1-2.
Representatives downloaded but not decoded (Mac off-limits): ATLANTIC PARK 645f62bc74, 3602_MTSU 7059354edd (+IFC),
0683-QCPS d69ba800a9, 7.98 CBMAA 15f863101f.

## 1b. Contour plates on 9.08 / 9.50 (float64 outline record) — biggest lift

9.08 and 9.50 keep contour outlines in a stride-465 record (same 2-hop link: part +29 -> stride-33 record +25) as **float64**:
u[10] @25, v[10] @105 (w @185), chamfer x/y float32 @265/@305, chamfer type int32 @345 (INT_MAX after the last point).
`find_polygons` tries this layout only when the float32 detection found nothing (`poly_f64` in the layout).
* Today **every 9.08 model writes 0 contour plates**: Disk-1/2 233/234 OK 9.08 models, 230,155 plates skipped as
  contour_plate_no_outline; data-4 116/128 models, 126,782 plates.
* 9.08 f34e32d507 vs Tekla IFC (GUID join): **531/531 contour plates exact** (centroid <= 1 mm, area <= 1 %); smoke convert
  0 -> 532 contour plates written. 9.08 p9.08 61/61 outlines; 9.08 3089c30191 17/17.
* 9.50 011ad596ea: 1,616/1,619 outlines (no IFC for 9.50; extent == part length on 1,592/1,595, type arrays close with INT_MAX).

## 2. Writer statuses (`db1step.patch`)

* **suspect_attr_link** (43 x 8.85, one project): the COLUMN-name heuristic misfires on railing/stair models. In that model's
  own Tekla IFC 54 of 68 COLUMN-named parts are horizontal (our col_vertical 0.189 matches). The hold now stays only when the
  naming-independent checks fail (`attrlink.py`): plate-named parts own outlines matching their length (36/36 on both samples),
  ANTIMATERIAL parts are cut-relation children. A wrong link fails both by construction.
* **empty_model**: (a) 7.30: all 11 Disk-1/2 7.30 NML files are model templates (7-57 KB, 0 part attributes); real 7.30 models
  already decode in db1old (data-3 7c82c44be6: 37,987 parts, axis 1.0). (b) no point table and < 50 part records under the
  normal and the flag-1 variants: reference-model / drawing-only models (8.07 STAIR COORDINATION e011e3f7f2, 3ef2ec016b).

## 3. Tekla fittings and line cuts (`fittings.py`, `step/db1step.patch`) — handed to the cut-not-applied owner, NOT in handoff_v2

Found: relation records (stride 69, the cut relation table) **type 9 = fitting**, **type 12 = line cut**; parent part @17,
child object @21. The child is a record (stride 49 on 7.64-9.08) with int @13 = a csys key in the stride-61 'after' table and
doubles @17/25/33 = a point on the plane; plane normal = x cross y of that csys.
* fitting: removes the part on the far side of the plane from the part middle (Tekla IFC: extrusion shortened + half-space).
* line cut: removes the +normal side.
* type 34 objects have the same signature but match no IFC cut (not cuts; ignored).

Writer: perpendicular fittings on profile extrusions trim the member (exact, no boolean); oblique fittings, fittings on plates
and line cuts are subtracted as half-space boxes (2(L+2 m) wide) through `IfcOut.element(cuts=...)`. `DB1_FITTINGS=0` turns it off.

Validation vs Tekla IFC (GUID join):

| engine | fitting planes matched | line-cut planes matched | parts within 1 mm (bbox in part frame) without -> with | parts worsened |
|---|---|---|---|---|
| 7.64 | 285/294 (vertex test) | — (none in sample) | 1,156 -> 1,249 / 1,560 (153 improved) | 0 |
| 8.07 (2 models) | 24/24 | 85/85 | 593 -> 605 / 605; 365 -> 381 / 391 (12 + 16 improved) | 0 / 0 |
| 8.53 | 48/48 | 6/6 (brep vertices) | 1,633 -> 1,653 / 2,493 (23 improved) | 0 |
| 8.85 | 77/78 | 63/63 | 707 -> 758 / 838 (58 improved) | 0 |
| 9.08 | 67/82 (IFC rotated 180 deg; rigid fit) | 50/51 | — | — |
| 7.82 | pair not usable (rigid-fit residual 30 mm; different revision) | | | |

Remaining part mismatches with fittings on are other causes (stud heads, plates in a different revision, etc.).

## 4. Engines 9.21 / 9.50

Geometry fields = 9.08 (9.08 vs Tekla IFC 8ec3ba13c9: 1,014/1,074 joined members exact at both ends; the rest are model
revisions). Attribute record: stride 381, profile @125, tail ref @189 -> stride 54 @25 (found by `_semi`; the
`_deepdive/db1-axis-guard` agent found the same).
* 9.21 254a5fdd9e 1,618/1,618 profiles, axis 1.0; data-3 a95d70a898 1,066 members / 1,048 profiles; c4bf00c134 empty.
* 9.50 011ad596ea 8,298 members, 7,646 profiles (652 Hilti anchors with '3/4"_' names cannot pass the strtok identity).
* OPEN: 9.50 contour-plate outline link (1,619 plates -> contour_plate_no_outline).

## Coverage table (engine / variant -> tested, decoded, accuracy vs truth)

| engine / variant | models tested | members decoded | accuracy vs Tekla IFC (GUID join) |
|---|---|---|---|
| 7.64 (fixed layout, unchanged) | 3 | 390 / 3,099 / 2,216 | regression identical; fittings 285/294 planes |
| 7.82 (unchanged) | 1 | 1,045 | regression identical (truth pair 7.82 unusable: other revision) |
| 8.07 (unchanged) | 3 | 1,681 / 451 / 665 | HDK 1681/1683 (earlier); p807: 97-98 % members exact, 100 % with fittings |
| 8.07 flag1 (NML) | 1 | 9,321 | plates 1,242/1,242; member profiles 879/879; axes collinear 97.8 % (ends = fittings) |
| 8.07 reference-model only (NML) | 2 | 0 | -> empty_model |
| 8.44 / 8.53 (unchanged) | 1 / 1 | 1,376 / 3,278 | regression identical |
| 8.85 (unchanged) | 2 | 2,453 / 1,299 | regression identical |
| 8.85 spread (NML) | 1 | 1,781 (1,780 written, 367 plates) | no IFC in folder |
| 8.85 geo (NML, CBMAA family) | 1 | 32,788 | axis agreement 1.0; folder IFC has no extruded bodies |
| 8.85 suspect_attr_link | 2 | 3,816 / 2,985 | IFC: COLUMN names really horizontal (54/68); evidence 36/36 plates, 265/265 cuts |
| 9.08 (+ float64 plates) | 3 | 1,268 / 1,917 / 1,225 | members 1,014/1,074 exact (rest = revisions); plates 531/531 |
| 9.21 (new layout) | 3 | 1,618 / 1,066 / 0 | no IFC; profiles 100 %, axis 1.0 |
| 9.50 (new layout + float64 plates) | 1 | 8,298 (7,646 profiles), 1,616/1,619 plates | no IFC |
| 7.30 | 2 | 37,987 (real model, db1old) / 0 (template) | templates -> empty_model |

Untested (heavy, need BOX-B): NML families ATLANTIC PARK (42), 3602_MTSU (26) + MTSU academic (8), 0683-QCPS (21), Dry Dock (4),
7.98 CBMAA (5), 9.08 Intel CUB2 (3 x 291 MB); 9.21 main data-3 model 2ffffe4d1d (on the builder's fleet now). `box/jobs_d4.json`
lists all 263 data-4 non-ok DB1 jobs for `box/selfcheck.py`.

Open: 8.85 models with a few plates without outline (Disk-1/2: 107 models with > 20, e.g. Glenlake III 5,942 of 7,319) - not
investigated. 9.50 Hilti anchor names (strtok identity). Fittings / line cuts handed to the cut-not-applied owner (section 3).

## Blocked

Running jobs on BOX-B via SSM was denied by the auto-mode classifier ("Remote Shell Writes") for this agent. The job driver is
ready in `box/` (boxdrive.py + boxrun.sh) but was not staged or launched. Needs the user's decision.
