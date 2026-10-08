# ifc-volume-residue — 'ifc volume tolerance' (178 IFC rows) + 'db1 volume tolerance' (13 rows)

Base: ifc2step6 **6.1.0-dev3** (`s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcv6/ifc2step6_dev3.py`,
md5 f23651e819ec959abb0619fc4a3ae9d0). All conversions, read-backs, census runs and kernel probes ran on BOX-A
(i-0c694360a18d7759f) under `/work/agentwork/ifc-volume-residue`; results in
`s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/{dev3,dev3p,dev3pc,diag}/`
(per model: case.json, stats, sidecar, census, src/step parts, attrib.json, fullscan.json; STEP files and inputs were
removed from the box after the run).

Deliverables (this directory, also under `s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/pfix/ifc-volume-residue/`):

| file | what |
|---|---|
| `ifc2step6-dev3_opening-contact-walls.diff` | **converter patch 1** vs dev3: opening shells with contact walls (applies unchanged to dev4, 6.1.0-rc, 6.1.1-dev) |
| `ifc2step6-dev3_null-curve-segments.diff` | **converter patch 2** vs dev3: composite-curve segments without a ParentCurve (`#0`) (independent of patch 1; both apply together and to dev4 / rc / 6.1.1-dev) |
| `ifc_census-v3_quantity-basis.diff` | **grader patch for the builder** vs the kit's `ifc_census.py` (census v2 -> v3); not deployed |
| `ifc2step6_dev3+openfix+curvefix.py` | convenience test build = dev3 + patch 1 + patch 2 (md5 758c924764730c8db26c9e754975d528); not for the kit |
| `tools/` | attribution / fidelity / census-evaluation scripts used for the evidence below |

## 1. What the 178 rows are

Live index (2026-10-02T00:06Z): 165 class 2 + 13 class 3. Authoring tool (census `applications`): SDS/2 139, Revit 30,
Tekla 9. 157 are **reused v5 STEP files** (disk-1/2, `ifc2step5`), 21 fresh `z3-ifc-2026-10-01a(+s6)` results of which only
4 actually ran ifc2step6. **141 of the 178 were graded with census v1** (no opening check, old RHS / T formulas).

## 2. Re-run of 37 affected models with dev3 (FIRST step of the item)

37 models picked over every failure pattern of the 178 (SDS/2 plates at 0.92-0.95, Revit walls / slabs / split columns,
Tekla 'net' quantities, bolt assemblies x350, welds x12, d453 double geometry x52, ...), 0.08-22 MB. Each ran through the
fleet worker's own `process()` (conversion ladder, step_check read-back, kit census v2, grade_join) and
`build_index.classify_ifc()` with the live `rules.json` (`run_case2.py`). Then every part outside the band was attributed
(`attrib.py`: exact ifcopenshell/OCC B-rep volume with and without openings vs STEP vs census), and every part of every
model was checked for converter fidelity independent of the census (`fullscan.py`: STEP read-back volume vs exact B-rep).

Outside-band parts (non-curved > 5 % + curved outside 0.90-1.05), same 36 models (761b excluded, see 5.3):

| | parts outside | models with outside parts |
|---|---|---|
| live (old STEP + the census it was graded with) | 2 912 | 31 |
| census v2 on the **old** STEP (no reconversion) | 2 588 | 19 |
| **dev3** STEP + kit census v2 | **931** | 6 |
| dev3 + converter patches 1+2 + census v2 | 931 | 6 |
| dev3 + patches 1+2 + **census v3** (proposed) | **5** | 2 |

Fidelity of the dev3 STEP itself (`fullscan`, 33 models, 58 787 parts; 113 without a solid or an exact volume): 58 593
within 1 % of the exact B-rep (3 % for `approx-curved`), 81 outside: tagged stand-ins (open-surface 40, L3 3), Revit
round HSS tessellation (23, `approx-curved`, +3.9..4.2 %, 5.1), SDS/2 'd' deck envelopes from double-sided meshes (8,
5.4), transcoded faceted bodies where the kernel's own B-rep differs by 1.7-2 % (pp1201 / pp1202 in two models, bp236;
the STEP keeps the source vertices), an opening-cut sliver (hss266, 949 mm3), and the kernel boolean failure of 5.2
(ANGLE).

**Conclusion: after reconversion with dev3 the 'volume tolerance' residue is a grader (census) problem, not a converter
problem**, except the items in 4 and 5.

Per model (live = the index row as graded today; dev3 / patched = this run through the fleet worker + classifier; census v3 = the proposed census on the same STEP; 'oom' = the dev3 memory blow-up of 5.3):

| model | grp | MB | class live | vol outside live | class dev3 | vol outside dev3 (census v2) | class dev3+patches | vol outside census v3 | class dev3+patches + census v3 | other blockers |
|---|---|---|---|---|---|---|---|---|---|---|
| c951cd2d377ddbd0 | A | 0.1 | 3 | 13/14 | 1 | 0/16 | 1 | 0/16 | 1 |  |
| 7081379989466f7a | A | 0.2 | 3 | 4/4 | 1 | 0/67 | 1 | 0/67 | 1 |  |
| e43ef513774563bb | A | 0.3 | 3 | 36/40 | 1 | 0/63 | 1 | 0/63 | 1 |  |
| aa33931d26f7b00f | C | 0.4 | 2 | 1/27 | 2 | 0/3 | 1 | 0/3 | 1 |  |
| e747269a560d4ab0 | A | 0.4 | 2 | 100/122 | 1 | 0/176 | 1 | 0/176 | 1 |  |
| 62183869f989ddad | B | 0.5 | 2 | 1/3 | 2 | 0/39 | 2 | 0/39 | 2 | parts_without_solid, v6_open-surface |
| 9d37129fa2e8215f | A | 0.5 | 2 | 17/25 | 1 | 0/73 | 1 | 0/73 | 1 |  |
| 6c34c866aeb21125 | D | 0.7 | 2 | 1/232 | 1 | 0/231 | 1 | 0/252 | 1 |  |
| cd3313dc0284fc2f | A | 0.8 | 3 | 63/87 | 2 | 0/173 | 2 | 0/173 | 2 | v6_open-surface |
| f582bf9375d82ab7 | A | 1.0 | 2 | 108/130 | 2 | 0/218 | 2 | 0/218 | 2 | v6_open-surface |
| 58fca78db193f08c | G | 1.0 | 2 | 1/39 | 2 | 0/276 | 2 | 0/276 | 2 | parts_without_solid, v6_open-surface |
| 6014d0b56d6c2e69 | B | 1.2 | 2 | 1/29 | 1 | 0/153 | 1 | 0/153 | 1 |  |
| 7011945e4a00cdba | B | 1.3 | 2 | 3/36 | 1 | 0/156 | 1 | 0/156 | 1 |  |
| 4cf69f431396f2a4 | B | 1.4 | 2 | 5/22 | 2 | 0/28 | 2 | 0/28 | 2 | parts_without_solid, v6_L4-surface |
| 477710ac34d08610 | C | 2.3 | 2 | 94/315 | 2 | 0/67 | 2 | 0/67 | 2 | parts_without_solid, v6_open-surface |
| 6add5339c9184554 | B | 2.8 | 2 | 4/55 | 1 | 0/7 | 1 | 0/9 | 1 |  |
| 224b42bfc48cf6d2 | C | 3.7 | 2 | 124/617 | 2 | 0/346 | 2 | 0/346 | 2 | parts_without_solid, v6_L4-surface, v6_open-surface |
| 40e3d7899994b307 | C | 3.9 | 2 | 138/388 | 2 | 0/171 | 2 | 0/171 | 2 | parts_without_solid, v6_L4-surface, v6_open-surface |
| 3a5129c14f17f9b0 | C | 3.9 | 2 | 227/904 | 2 | 227/904 | 2 | 0/911 | 1 |  |
| bf768f1f03f316a1 | D | 4.0 | 2 | 3/409 | 1 | 0/409 | 1 | 0/661 | 1 |  |
| f4c19f2e17e8e3c4 | E | 4.0 | 2 | 338/1432 | 2 | 3/1432 | 2 | 3/1432 | 2 | v6_L3-partial-surface |
| aa1e8467bb71402e | D | 4.0 | 2 | 4/419 | 1 | 0/416 | 1 | 0/670 | 1 |  |
| 8409d3886233a18a | B | 4.5 | 2 | 3/167 | 1 | 0/283 | 1 | 0/283 | 1 |  |
| 68b330d334f10433 | C | 5.5 | 2 | 3/1263 | 2 | 0/1263 | 2 | 0/1263 | 2 | v6_L4-surface, v6_open-surface, coverage_0.9993 |
| aa2643a3dce3c010 | D | 6.7 | 2 | 2/718 | 2 | 0/736 | 2 | 0/1155 | 2 | parts_without_solid |
| 761b25e0fe15219f | F | 6.8 | 2 | 279/1092 | 3 | - | - | - | 3 |  |
| d453e331f82315cd | E | 7.8 | 2 | 638/868 | 2 | 0/867 | 2 | 0/867 | 2 | parts_without_solid, v6_open-surface |
| 83b0ffca8608124f | D | 8.1 | 2 | 297/2037 | 1 | 0/1747 | 1 | 0/1876 | 1 |  |
| 03af2c3170d9a570 | C | 8.3 | 2 | 81/6567 | 2 | 81/6567 | 2 | 2/6567 | 2 | parts_without_solid, v6_open-surface |
| e5f30a12ecc5f3e5 | E | 9.6 | 2 | 333/6294 | 2 | 353/8297 | 2 | 0/7939 | 1 |  |
| b4efa46d5914068e | E | 10.9 | 2 | 236/1951 | 1 | 0/1951 | 1 | 0/1951 | 1 |  |
| 0a2c43d06678a61b | C | 11.7 | 2 | 79/11198 | 2 | 79/11198 | 2 | 0/11198 | 1 |  |
| 52246ea35ba4f14b | F | 12.6 | 2 | 24/252 | 2 | 0/1355 | 2 | 0/1355 | 2 | parts_without_solid, v6_L4-surface, v6_open-surface |
| f356b275dd5993f2 | F | 13.2 | 2 | 202/12434 | 2 | 188/12434 | 2 | 0/12434 | 1 |  |
| b70347bbc5734a76 | F | 14.3 | 2 | 35/710 | 2 | 0/710 | 2 | 0/710 | 2 | parts_without_solid, v6_open-surface |
| cdc69c9831ef0d41 | F | 20.3 | 2 | 45/721 | 2 | 0/721 | 2 | 0/776 | 2 | v6_open-surface |
| e6e3894bb8cd8165 | F | 22.4 | 2 | 8/826 | 2 | 0/826 | 2 | 0/1211 | 2 | invalid_solids, parts_without_solid, v6_L4-surface, v6_open-surface |

Class-1 count over the 36 converted models: live 0, dev3 14, dev3 + patches 15, dev3 + patches + census v3 19 (patched = both patches for the 7 models of the combined run, patch 1 for the others; patch 2 is a no-op there: no composite curve with an empty segment).

## 3. Root causes and where each is fixed

| # | cause | rows / evidence | fixed by |
|---|---|---|---|
| A | v5 STEP geometry: Body+Facetation summed (d453: x52.25), multi-lump shells -> negative / inside-out solids, openings missing on faceted bodies (SDS/2 plates 0.92-0.95), bolt assemblies x350, welds x12 | 157 reused rows | reconversion with ifc2step6 >= dev3 (already in dev3) |
| B | census v1: analytic volume ignores openings, old RHS / T formulas | 141 of 178 rows have census v1 | census v2 (kit already v2): reconversion or the final-pass `census` job (`build_index.final_jobs`) |
| C | Tekla `NetVolume` of CUT parts is on the profile **without root fillets / corner radii** (body has them): RHS 0.908 (HSS2x2x1/4) / 0.9415 (HSS3x3x1/4), W 1.083 (W10x12) = exactly A(radii)/A(sharp); uncut parts carry the body volume | 4 Tekla models: 2 983 cut parts rebased; with D their outside count 701 -> 2 | **census v3** rebases q by the profile's own parameters |
| D | Tekla round bars joined by UNION (sag rods, anchor bolts): NetVolume on an inscribed polygon whose side count depends on the diameter (0.9003 = 8-gon at 5/8", 0.9549 = 12-gon at 1 1/2") | e5f3: 358 parts | **census v3** drops q (kept as `q0`) |
| E | Revit "split by level": every segment repeats the parent element's BaseQuantities (same name `...:<ElementId>`, same value): segment / q = 0.03 .. 0.88 | 3a51: 283 parts | **census v3** drops q for such groups |
| F | Revit framing / columns are IfcArbitraryClosedProfileDef / WithVoids bounded by IfcCompositeCurve (lines + trimmed circles): census had no analytic value and fell back to Revit GrossVolume (unjoined length, family area) | 3 955 parts newly get `an` in v3 (Revit, Tekla, SDS/2 v7.3x), all matched ones within band | **census v3** computes those areas exactly (Green's theorem incl. arcs, voids) |
| G | **converter: product lost** - SDS/2 countersunk / stepped bolt holes are one IfcFacetedBrep holding cone + cylinder that touch face to face (16 edges used 4x); OCC's boolean with that tool returns nothing, the whole plate disappears | 224b: 28 plates, aa33: 1 plate (coverage 0.9808 / 0.983); 6.0.1 (fleet) loses them too | **converter patch 1** |
| H | kernel boolean failure in long DIFFERENCE chains: ifcopenshell returns the uncut first operand (BEAM 1XVwX2000lHp4sCpKtDZ8m: cut 4 of 11 fails -> 4.12e6 mm3 = base) or a partial result (ANGLE 1XUzTS000MM34sCpKrCZ8v: last clip fails -> 0.434e6 vs 0.359e6 step-by-step) | 2 parts in 03af | not patched (5.2) |
| I | Tekla open-web joist 'J1' (one FacetedBrep, 168 faces): fails volume cross-check at L0/L1/L2 -> L3 partial surface (tagged); STEP solid = 0.5085 of the body | f4c1: 3 parts | owner of solid repair (ifc-surface-to-solid / IFC improver) |
| K | **converter: product lost** - Tekla 2017i 'SHEAR TAB' profile = IfcCompositeCurve with one segment whose ParentCurve is `#0` (reference to no entity) plus a closed polyline; the kernel rejects the profile, the plate is dropped (kernel_pass missing 2) | e5f3: 2 plates, coverage 0.9997 | **converter patch 2** |
| J | db1: 11 rows are old disk-1/2 STEP graded by name join (outliers x354 PL20, x491 C10X15.3) and 2 are code f (3 plates at 0.6036 each) | 13 rows | db1 pipeline's own reconversion (codes h / i / j): every reconverted row 0 outside (5.5) |

## 4. Converter patch 1: opening shells with contact walls (`ifc2step6-dev3_opening-contact-walls.diff`)

Root cause (G): `hole-*` IfcOpeningElements of SDS/2 v2020 exports are one IfcFacetedBrep (IfcMappedItem, 36 faces) made of
a frustum (countersink, r 9.53 -> 4.76 mm) and a cylinder (r 4.76 mm) that touch along a 16-gon; the 16-gon is in the
shell twice with opposite winding. The shell is not 2-manifold, ifcopenshell/OCC subtracts it from the plate and the
result is EMPTY (verified with every kernel option: reorient-shells, boolean-attempt-2d, both meshers). dev3's `on_shape`
then gets no faces and the plate is silently missing (`parts_without_geometry`).

Fix: before the kernel pass, `repair_opening_shells()` walks the opening bodies of the kernel-bound products (through
mapped items and boolean operands), finds face pairs that cover the same polygon with opposite winding, and removes both
copies from the in-memory IfcClosedShell - the same contact-wall rule the transcoder already applies to product shells
(the two bodies become their exact union; no face added, no vertex moved, the source file untouched). A shell is changed
only when that makes it 2-manifold where it was not. Opt-out `V6_NO_OPENING_REPAIR=1`; `stats.opening_shell_repair`
records openings / shells checked / repaired / pairs removed.

Before / after on real models (BOX-A, worker + classifier as the fleet runs them):

| model | dev3 | dev3 + patch |
|---|---|---|
| aa33931d26f7b00f (SDS/2 2020.04) | 58 parts, plate 2P1525 missing, coverage 0.983, **class 2** | 59 parts, coverage 1.0, **class 1** |
| 224b42bfc48cf6d2 (SDS/2 2020.10) | 1 435 parts, 28 plates (301CP1-14, 301SP1-14) missing, coverage 0.9808 | 1 463 parts, coverage 1.0 (class 2 remains: open-surface 7, L4 1) |

Recovered plates are level-0 exact solids, BRepCheck valid; removed volume = 0.94-0.975 x the openings' own volume (the
holes protrude 0.13 / 0.25 mm beyond the plate faces) on all 21 listed plates - i.e. the holes are cut, nothing else.
Regression over the other 34 models: no part lost, no part volume changed (gid-joined step_parts identical), no class
change; the only differences are the recovered parts.

### 4b. Converter patch 2: composite-curve segments without a ParentCurve (`ifc2step6-dev3_null-curve-segments.diff`)

Root cause (K): `#39846=IFCCOMPOSITECURVE((#39841,#39845),.T.)` with `#39841=IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,#0)`
- a mandatory attribute pointing at no entity (ifcopenshell reads it as $) - next to `#39845` = the closed polyline (0,0)-(457.2,0)-(457.2,304.8)
-(-203.2,304.8)-(-203.2,0)-(0,0) that alone bounds the plate. ifcopenshell fails the whole profile ("Failed to process
shape", also with no-wire-intersection-check / precision variants), the product has no geometry and is dropped.
Fix: right after parsing, `repair_null_curve_segments()` drops segments without a ParentCurve from in-memory
IfcCompositeCurves that keep at least one real segment (no geometry removed - the segment has none; source file untouched).
`stats.null_curve_segments_dropped`; opt-out `V6_NO_CURVE_REPAIR=1`. With it the kernel builds both shear tabs at
3 834 573.4 mm3 = 660.4 x 304.8 x 19.05 (the polyline's own rectangle x depth); 1 of 500 composite curves in that model
had such a segment, and none of the other 36 sample inputs has one (patch 2 is a no-op there).

Both patches together (combined file = dev3 + patch 1 + patch 2), 7 models:

| model | dev3: class / coverage / parts / no geometry | dev3 + patches 1+2: class / coverage / parts / no geometry | opening_shell_repair | null_curve_segments_dropped |
|---|---|---|---|---|
| 03af2c3170d9a570 | 2 / 1.0 / 7171 / 0 | 2 / 1.0 / 7171 / 0 | 0 of 0 shells | 0 |
| 0a2c43d06678a61b | 2 / 1.0 / 11624 / 0 | 2 / 1.0 / 11624 / 0 | 0 of 0 shells | 0 |
| 224b42bfc48cf6d2 | 2 / 0.9808 / 1435 / 28 | 2 / 1.0 / 1463 / 0 | 1 of 1 shells | 0 |
| 3a5129c14f17f9b0 | 2 / 1.0 / 932 / 0 | 2 / 1.0 / 932 / 0 | 0 of 0 shells | 0 |
| 83b0ffca8608124f | 1 / 1.0 / 5359 / 0 | 1 / 1.0 / 5359 / 0 | 0 of 0 shells | 0 |
| aa33931d26f7b00f | 2 / 0.983 / 58 / 1 | 1 / 1.0 / 59 / 0 | 1 of 1 shells | 0 |
| e5f30a12ecc5f3e5 | 2 / 0.9997 / 8297 / 2 | 2 / 1.0 / 8299 / 0 | 0 of 0 shells | 1 |

Per-part comparison dev3 vs combined (gid-joined step_parts): models 7 class changes [('aa33931d26f7b00f', [2, 1])] vol changes 31 new parts 31 lost 0.

## 5. Not patched (evidence for the owners)

5.1 **Tessellation**: round bars (S/X 0.985) and thick round HSS (polyhedral output meshes the inner circle coarser than
the outer: S/X 1.042 on Revit HSS6x0.500) come from the worker's `ANG_DEFLECTION=0.6`; both stay inside the grader's
curved band; all such parts are `approx-curved`.

5.2 **Kernel boolean failures (H)**: walking the DIFFERENCE chain item by item with `create_shape` shows the failing
operation (BEAM: operand #50447, d=378, returns the base 0.0041199737 m3 and every later step keeps it; ANGLE: the last
IfcHalfSpaceSolid returns 0.000434 after 0.000359). `precision-factor` 0.1..1000 and `boolean-attempt-2d` do not change
it. Census v3 exposes them (Tekla) as the only remaining volume failures; SDS/2 / Revit have no quantity to expose them.
Cheap detector for the IFC improver: kernel volume of a DIFFERENCE-tree product equal to its base extrusion while an
operand intersects it, or larger than the result of `top.FirstOperand` -> tag `[approx: cuts not applied]`.

5.3 **761b25e0fe15219f (SDS/2, 6.8 MB)**: dev3 grows to 233 GB RSS in 17 min inside `ifcopenshell.geom.iterator.next()`
(kernel pass, 2 threads; killed by me). With 1 thread / 20 GB cap it stalls after 157 shapes; `create_shape` of the
'ab18' angles (L4x3x1/4 with one extruded hole each, products #1075-#1081) fails after 7-11 s with "An unknown error
occurred". In the fleet the job would end `out_of_memory` (memory kill is not routed to `ifc_crash_bisect`). Kept for
the IFC improver; the live best-of result (v5) stays.

5.4 **double-sided closed meshes as solids** (dev3 behaviour, informational): SDS/2 v7.331 'd###' IfcMembers in
b70347bbc5734a76 (every face given twice) now read back as solids of 2.3e9 .. 1.4e11 mm3 (d267: 27.5 m x 0.13 m x 41 m
envelope); the kernel's own B-rep volume of those items is 0. No census expectation exists for them, so the grader
cannot see it either way.

5.5 **db1** (13 rows): 6 already reconverted by the db1 pipeline (0f36 i, 7a6a j, 2915 j, 4518 h, 86cf h, a81d i): **0
parts outside** in each (51 738 / 51 728 / 1 294 / 13 495 / 1 603 / 1 603 checked); the other 7 are in its reconvert
queue (siblings of fixed rows). One curved-gross remains: 4518 PIPE1-1/2STD 0.13 mm long (an 67.5 mm3, STEP 71.5): the
0.01 mm output grid is 7.7 % of its length.

## 6. Grader changes for the builder (precise)

G1 - **refresh census v1 rows**: 141 of the 178 rows were graded with census v1; run the existing final-pass `census` job
(or let the reconvert queue rerun them) - alone it removes 324 of 2 912 outside parts in the sample (2 588 left, 19
models); with the dev3 reconversion 2 912 -> 931 (6 models).

G2 - **ifc_census v3** (`ifc_census-v3_quantity-basis.diff`, CV=3; tested on the 36 sample models: 931 -> 5 outside,
3 955 more parts get an analytic value, all matched ones within band, no new outlier):
  * `prof_area`: IfcArbitraryClosedProfileDef / IfcArbitraryProfileDefWithVoids bounded by IfcPolyline, IfcCompositeCurve
    (IfcPolyline, IfcTrimmedCurve on IfcCircle / IfcLine; SameSense, SenseAgreement, cartesian or parameter trims in the
    file's plane-angle unit) or IfcIndexedPolyCurve (IfcLineIndex / IfcArcIndex): area by Green's theorem with exact
    circular-arc terms, voids subtracted.
  * Tekla (`IfcApplication` contains 'Tekla'), q kind `net`, body = one boolean tree with DIFFERENCE all along the first
    operand ending in an IfcExtrudedAreaSolid whose profile has radii (I FilletRadius, RHS corner radii, L / T fillet):
    `q = q * A_with_radii / A_sharp` (both from the profile's own parameters); record `q0`, `qx =
    tekla_cut_part_sharp_profile_basis`.
  * Tekla, q `net`, boolean tree containing UNION whose material extrusions are all IfcCircleProfileDef: q dropped
    (`q0`, `qx = tekla_union_round_bar_polygon_basis`).
  * Revit: products whose Name ends in `:<digits>` and share (Name, quantity kind, raw value) with another product
    (evaluated before the openings rule): q dropped (`q0`, `qx = revit_split_element_shared_quantity`).
  * summary: `quantities_rebased` counts. grade_join needs no change (v3 records satisfy `cv >= 2`).

G3 - **build_index.vol_issues** (cosmetic, optional): do not count parts whose STEP description carries
`L3-partial-surface` / `L4-surface` in the volume check (already a blocking stand-in; f4c1's 3 joists are counted twice).

G4 - **slivers** (db1 4518): skip the +-5 % test for parts with an expected volume < 1 000 mm3 or a smallest bbox extent
< 1 mm (100 x the 0.01 mm STEP grid); report them separately.
