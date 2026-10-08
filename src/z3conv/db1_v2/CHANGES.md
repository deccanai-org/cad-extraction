# db1 v2: Tekla DB1 decoder, new-engine bolt groups (7.5x–8.x)

Drop-in for the z3conv db1 kit (`_control/z3conv/db1/`). `convert_one.py` CLI and worker interface are unchanged.

v2 = **the builder's current kit + `apply_v2_patch.py`**, which inserts the v2 block (`v2_convert_block.py`) into `db1step._convert`.
Re-run it on every builder update: `python3 apply_v2_patch.py <kit_dir> <out_dir>`. Old engines (6.47–7.30, `convert_old`, builder's
`db1bolts.py`) are untouched.

## New files

| File | What |
|---|---|
| `db1bolts2.py` | Bolt-group decoder for the record-discovered engines + placement / hole planner (interface = builder's `db1bolts` bolt dicts) |
| `tekla_bolt_assemblies.json` | Tekla's own head / nut / washer dims per (bolt standard, d), harvested from 2,500 Tekla IFC exports (635 entries; mode + share + provenance) |
| `ifc_unhole.py` | Crash-bisect fallback: strip only the `BOLT_HOLE_*` subtractions from culprit elements (part kept, holes tagged uncut) |
| `apply_v2_patch.py`, `v2_convert_block.py` | Rebase tool + the `_convert` block |
| `run_conv.py`, `validate_bolts.py`, `validate_place.py`, `regress/regress.py` | Validation / regression tools (not needed by the worker) |

## Changed

- `db1step._convert` (engines ≥ 7.5): bolt-group records are no longer counted as members.
  - 8.x: they were `no_profile` members.
  - 7.x: they were `bolt_group_excluded`.
- Each group is decoded and written:
  - bolts → one `IfcMechanicalFastener` per group, via `IfcOut.bolt_group`;
  - holes-only groups → `holes_only_group`;
  - groups that cannot be placed → `bolt_group_unplaced` (skipped, counted, never guessed).
- Holes (`BOLT_HOLE_D<d+tol>`) are cut as `IfcBooleanResult` DIFFERENCE in:
  - the parts the group is related to (type-10 relations);
  - only where the bolt axis passes through the part's exact section;
  - only within the grip (7.x: recorded; 8.x: within the bolt's search length).
- `db1bolts.standard_geometry` (every engine, incl. the builder's old-engine `bolts_of`) is now:
  1. Tekla's own dims harvested from Tekla IFC exports (exact standard name → verified alias → name prefix);
  2. the standards tables. ASTM table hits also get Tekla's F436 washer from the harvest.
- `catalog_geometry` (the model's own screwdb/assdb) still comes first in the writer.
- `washer_dims` / `washer_exact` accept `source` in (`model_catalog`, `tekla_harvest`, `table+tekla_washer`).

## Reverse-engineered record semantics (validated against Tekla IFC exports joined by GUID)

GUID join:
- Tekla stores each object's GUID string in a 72-byte record keyed by the object key: `[objid][ref][04][key@+9]…[GUID@+33, optional 'ID' prefix]`.
- The Tekla IFC `Tag` is `ID<guid>`, so every IFC element joins to its DB1 record exactly.

Bolt group:
- A member-like record whose attribute record has **obj_type 10 @+13**.
- Group record table:
  - 8.85 / 9.08: split over records keyed by the group key:
    - header (33-byte table): `attr@13 ?@17 p1@21 p2@25 pattern@29`;
    - placement (49-byte table): `csys@13 origin@17 L@41` (doubles).
    - Validated on 8.85 Amazon IAD 192: 13,089 / 13,138 joined groups resolve frame + attributes + pattern; axis = −z for 98.7%.
  - 7.x and 8.07: 65-byte member layout (`attr@13 p1@17 p2@21 pattern@25 csys@29 origin+L@33`);
  - 8.44 / 8.53: 73-byte layout (`attr@13 p1@21 p2@25 pattern@29 csys@33 origin+L@41`).
  - The segmenter can split the 65-byte table into multiple-stride runs (130, 195, …); both layouts are tried per run.
- Attributes:
  - 7.x bolt string in the part attribute table: `MM<d>*<L>/<slot x>/<slot y>/<tolerance>/<?>/<search length>/<grip centre z>/<?>/<flags>/<?>/<grip>`; bolt standard at +285.
  - 8.x / 9.x own table (stride 317 on 8.53 / 8.85, 321 on 9.08, 365 on 8.07). Offsets are 8.53-relative plus a shift read from the record's own 'SCREW' string (59 + shift; 0 for 317/321, 48 for 365). The table below is in 8.53 terms (S = 317):

    | Field | Offset |
    |---|---|
    | d | S-48 (f32) |
    | slot x | S-44 |
    | slot y | S-40 |
    | tolerance | S-36 |
    | grip centre z | S-24 |
    | search length | S-28 |
    | flags | S-16 (int) |
    | L | S-12 |
    | bolt count | +29+(S-317) |
    | special-hole parts bitmask | +21+(S-317) |
    | standard string | +165+(S-317) |

- Flags are decimal digits d5..d0: d5 = holes only; d4 = head washer; d3 = washer 2; d2 = nut washer; d1, d0 = nuts.
- Bolt positions: pattern record (stride 341, shared by identical patterns; 9.08: stride 465).
  - `u[10]@21, v[10]@61` (f32) in the group frame.
  - 9.08 (stride 465): `u[10]@25, v[10]@105` as float64, types at @345.
  - The count is the index of INT_MAX in `int[10]@221`.
  - More than 10 bolts continue in records with the same key, with the record index at +13.
- Frame: x, y from the csys (x signed toward the far layout point), z = x × y. The bolt axis is −z and the head is on +z.
- Head underside:
  - 7.x: z = grip centre + grip/2 (+ head washer);
  - 8.x: top of the plies of the related parts within the search length (+ head washer). It is checked against the stored grip centre.
- Relations bolt → parts: the part-cut relation table (stride 69), **type 10 @13, bolt @17, part @21**.
- Hole: diameter = stored d + stored tolerance.
  - Slot x/y are active only when the special-hole bitmask is non-zero.
  - Slots are currently cut as round holes and tagged until the part order behind the bitmask is verified.

## Accuracy vs ground truth (GUID-joined Tekla IFC exports)

See `REGRESSION.md`. The coverage table is filled from `valstage` (BOX-B) runs.
