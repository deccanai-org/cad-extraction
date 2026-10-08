# db1 v2 regression and ground-truth report

## 1. Ground truth

- **GUID join.** Every Tekla object's GUID is stored in its DB1 (72-byte record keyed by the object key). A Tekla IFC export carries the same GUID in each element's Tag (`ID<guid>`). This gives exact per-object truth for bolts and parts.
- **Pair scan.** Run in-region over Disk-1/2, data-4 and data-3 (11,881 DB1 jobs; partial):
  - Pairs with GUID join ≥ 0.8 and > 50 joined fasteners: 7.64 ×39, 7.82 ×11, 7.98 ×17, 8.07 ×321, 8.53 ×44, 8.65 ×4, 8.85 ×213, 9.08 ×17.
  - List: `work/truth_pairs.json`.
- **Coordinate frames.** Coordination exports are often shifted. The validators estimate one global translation (least squares on the in-plane centroid offsets of the joined groups); e.g. 7.82 MCA: (−101,307.9, −31,775.4, −30,480) mm.

## 2. Bolt accuracy vs Tekla IFC (latest code: raw-x frame + full-ply grip)

| Engine | Model (pair) | Bolt groups joined / IFC | Groups with every bolt ≤ 1 mm (xy) | Bolts ≤ 1 mm (xy) | Head (axial) ≤ 1 mm | d / hole / slot / washer / nut |
|---|---|---|---|---|---|---|
| 7.64 | E-45 Check | 4,759 / 4,781 | 4,532 (95.2%) | 10,102 / 10,900 (92.7%) | 98.3% (record) | d 100%, hole 92% |
| 7.82 | c73731fe0d | 1,089 / 1,089 | 1,039 | 1,654 / 1,658 (99.8%) on groups with a shank | 99.2% (record) | d / L / hole / slots 100% |
| 7.82 | 544 Lindell | 3,513 / 3,605 | 3,394 (96.6%) | 3,402 / 3,521 (96.6%) | **99.3%** (was 57.5% before the raw-x fix) | d / hole / slots 100% |
| 7.82 | MCA MOB (shifted IFC) | 3,726 / 3,726 | 3,299 (88.5%) | 12,831 / 13,422 (95.6%) | 98.0% ≤ 1 mm, 100% ≤ 5 mm | d 100%, hole 98% |
| 8.07 | 211b33df06 | 455 / 512 | 395 + 58 pure translations | 995 / 1,155 | 93.5% | 100% |
| 8.07 | Westover Hills | 6,716 / 10,618 | 6,667 (99.3%) | 10,985 / 11,103 (98.9%) | 98.0% | d / hole / washers / nuts ≥ 99.9% |
| 8.53 | 0575f7270f | 2,673 / 2,718 | 2,521 (94.3%) | 4,812 / 5,283 | 98.8% | d 99.96%, washers / nuts 99.7% |
| 8.53 | Bobby Jones MoldTek | 2,866 / 2,871 | 2,783 (97.1%) | 3,696 / 4,034 | 99.6% | d 100%, hole 97% |
| 8.53 | Continental | 4,629 / 5,042 | 3,890 (84%) | 5,329 / 6,599 | 97.6% | d 99.9%, hole 99% |
| 8.85 | Amazon IAD 192 (split records) | 13,128 / 13,138 | 12,253 (93.3%) | 26,795 / 28,561 (93.8%) | **100%** (12,794 bolts) | d / washers / nuts 100%, hole 99.3% |
| 8.65 | Giorgi USA | (GUID re-join pending) | | | 98.5% where the record grip centre agrees; 13% on the 1,126 bolts where it does not | |
| 9.08 | ASV Brain and Spine | 4,227 composite groups decoded (float64 patterns); 2,184 GUIDs not joined to a header | not measured (decode verified on samples) | | | |

Notes:
- Groups that miss are mostly constant translations that coincide with moved parts. The DB1 and the IFC are different model revisions; no translation field exists in the records.
- Head axial position is wrong in two places:
  - anchors (HILTI KWIK / expansion / epoxy), whose Tekla assembly geometry differs (3–13 mm);
  - 8.x groups whose grip centre disagrees with the record (flagged `bolt_axial_position_fitted`).

## 3. Members / plates (record layouts; from the engine-variant fork and earlier validations)

| Engine | Members | Plates |
|---|---|---|
| 7.64 | 3,860 exact on geometry (earlier validation) | outlines exact (7.82 family) |
| 7.82 | 75 / 77 + 13 / 13 IfcPlate outlines exact | |
| 8.07 | 1,681 / 1,683 exact (HDK). 31b6405d38 (flag1 variant): profiles 879 / 879, axis collinear 97.8%; the rest are fittings | 1,242 / 1,242 contour plates exact |
| 8.53 / 8.62 / 8.85 | layouts verified on IFC pairs (layouts.json `score`) | contour-plate outlines (2-hop link) exact |
| 9.08 | 1,014 / 1,074 joined members exact at both ends; the rest are later revisions | **0 → 531 / 531** contour plates (float64 outlines, engine fork handoff_v2) |
| 9.21 / 9.50 | 9.08 geometry fields; 9.21 sample 1,618 / 1,618 profiles, axis 1.0; 9.50 7,646 / 8,298 profiles. No IFC truth | 9.50 1,616 / 1,619 outlines (internal check) |
| Fittings / line cuts (type 9 / 12) | planes match IFC 501 / 526 and 204 / 205; +262 parts within 1 mm, 0 worse. Owned by the cut-not-applied fixer | |

## 4. Kit regression (BOX-B; builder kit code i/l vs kit_v2 on the same base; engines 7.5+; worker `_process_inner` + `build_index.classify_db1`)

Old engines (6.47–7.30, `convert_old`) are identical by construction: the patch touches only `_convert`. Measured identical on the first 4 data-3 6.87 models.

Partial results (the after-kit is slow on the shared box: holes add booleans; ifc2step6):

| Model | Before | After (first kit_v2) | Blockers after |
|---|---|---|---|
| 7.64 fb8e6c3cd4 | 1 | 1 | — |
| 7.62 493b39aa02 | 2 | 2 | catalog misses (C200*100*5, ISMB400, `<none>`); bolt tags (fixed in the update) |
| 9.21 a95d70a898 | 2 | 2 | `cuts_not_applied:462` (cut fixer), `v6_L2-alt-source:80`, catalog `<none>`; bolt tags (fixed in the update) |
| 7.82 4f7fa9df65 | 2 | 2 | `section_parametric_panel:54` (profile); bolt tags (fixed in the update) |

The bolt stand-ins on the first kit_v2 (`bolt_nominal_head_nut`, `hole_clearance_nominal`) were an accounting gap: the v2 block lacked the grader's bolt_stats keys. The kit_v2 update (shipped 01:05Z) emits them. On 7.82 4f7f: standard_table_geometry 36 / 36, holes_nominal_clearance 0, washers_nominal 0.
