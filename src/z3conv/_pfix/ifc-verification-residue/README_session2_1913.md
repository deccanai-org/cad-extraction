# pfix ifc-verification-residue (pipeline ifc, base ifc2step6 6.1.0-dev3)

Item: 'ifc per-part verification' pending (159 now), 'ifc members not converted' (16), 'valueerror' (15), plus evidence
on L2-alt-source parts still produced by dev3. Method: re-run the affected models with dev3 on BOX-A through the fleet's
own `worker.process` (conversion ladder, step_check read-back, ifc_census, grade_join) and the coordinator's
`classify_ifc` with the live `rules.json` (harness `job/rc.py`, `job/drive.py`). Then root-cause what remained, patch
dev3, and re-run the same models. Nothing was published; all runs wrote only under agentwork/ifc-verification-residue.

Base: `ifc2step6_dev3.py` (md5 f23651e819ec959abb0619fc4a3ae9d0). The fleet kit now runs `ifc2step6 6.1.0-rc`
(= dev4 = dev3 + cleanup), which has the same code at the patched places (kit lines 1702, 2044/2079). The IFC improver's
6.1.1-rc already merged my preliminary upload; see "Changes vs the preliminary upload" below.

## Files (s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/pfix/ifc-verification-residue/)

| file | what |
|---|---|
| `ifc2step6_dev3_verification-residue.diff` | converter patch, unified diff vs dev3 (A, E, F, G, far mode) |
| `ifc2step6_dev3+vr.py` | dev3 with the patch applied (VERSION `ifc2step6 6.1.0-dev3+vr`) |
| `worker_converter_readback.diff` | fleet worker hook (lead decision): per-part join from the converter read-back when the STEP is over the read-back cap |
| `step_check_far.diff` | grader rule (lead decision): far-from-origin files get their BRepCheck / volume checks from a translated second read |
| `sds2_v5.4_verify_step_render_guard.diff` | SDS2 v5.4 `decode/verify_step.py` render guard (KJL ValueError) |
| `results/*.md`, `results/l2_evidence/*.jsonl` | before/after tables, L2 evidence records |

## Converter patch (always on unless noted; each piece independent)

**E. Kernel products with openings meshed as triangles** (memory runaway; `V6_OPENINGS_POLY=1` restores dev3).
dev3 newly sends faceted products that have openings to the ifcopenshell kernel in POLYHEDRON_WITH_HOLES mode. On
Seaport L4 (beeeacea7d2d, SDS/2, 8,025 such products) dev3 reached 173 GB RSS in the kernel pass (killed). Root cause:
one product, angle a3717 (eid 8935, 02dnNiHvr9xext7h6RlJ8V: a 12-face IfcFacetedBrep minus two 18-face IfcFacetedBrep
hole prisms). Its polyhedral output exceeds a 12 GB address-space cap inside a single `create_shape` (bad_alloc), while
its TRIANGLE_MESH takes 0.14 s and gives a valid solid of 343,261 mm3 (352,670 without the openings). A 500-product
chunked iterator blew up on the same product, so the iterator itself is not the cause. Coplanar triangles are merged
back into the same exact polygons with holes by dev3's own `Repair.merge_coplanar`. With E, Seaport's kernel pass stays
at 1.3 GB, and the fleet kit (6.1.0-rc) has the same exposure: the Seaport and big SDS/2 Gateway jobs were claimed
around 01:10Z. Regression check: 10/10 L2 models are still class 1, with STEP sizes within 5 % and runtimes equal or
faster.
- **L2 for opening products is the polyhedral form, guarded.** With E, an opening product's L0 and its L2 alternative
  would both be triangle meshes. So L2 for these products is now the polyhedral form, run one product at a time
  (`create_shape`) under an address-space cap of the current size + `V6_GUARD_GB` (8 GB). A run-away then becomes an
  ordinary failure of that one product: in the variant test, bad_alloc surfaced as a catchable RuntimeError after about 6 s.
- **Gateway balance-of-plant** (af3c44bd, 4,929 opening products):

  | build | L0 | L2 | L4 | other |
  |---|---|---|---|---|
  | dev3 | 23,301 | - | 50 | - |
  | E without the guarded L2 | 23,290 | - | 60 | L3 1 |
  | final | 23,290 | 11 | 50 | - |

  On the final build, 61 products went through the guarded polyhedral L2 in 32 s with no failures. dev3's 50 L4 parts
  are kernel booleans on faceted bodies that come out as open shells; that is dev3 design, not this patch.
- **Baylor 7ff7ad6b:** part c559_1's triangle form fails OCC in place at 3e9 mm (far-origin noise). The guarded
  polyhedral L2 rescues it, so the model stays class 1 as on dev3.

**A. MAPPED_ITEM placement precision.** `emit_instance` wrote the translation with `%.10g` (10 significant digits): an
instance 3e9 mm from the origin was placed to the nearest mm, 2e8 mm to 0.1 mm (the grid is 0.01 mm). Now fixed point
with 6 decimals. No change below 1e7 mm.

**G. Every MAPPED_ITEM instance is verified at its own placement** (dev3 verified one instance per representation and
copied the verdict). OCC's verdict on a located shape depends on the placement: on Stockton (2c0f7a89, near the origin)
2 of 24 instances of pp20, with the same rotation as passing ones, fail the grader's read while dev3 passed all 24
(grader: invalid_solids:2). With G the two instances fail their own verification and are rewritten as copies
(dev3's L0b step), and the grader then reports no invalid solid (Stockton: invalid_solids:2 -> 0). The shared block is
written once per verification chunk (no duplicate entity ids). Verification time is unchanged on the 10 L2 models
(55.8 s vs dev3 65.6 s on the largest). Far instances without far mode keep dev3's behaviour (see far origin);
`V6_INSTANCE_DEDUP=1` restores dev3 fully.

**F. Per-part read-back export.** dev3 reads every written part back from its own STEP block with step_check's checks
but kept only pass/fail. The result for the representation actually written is now kept and written as
`<out>.verify_parts.jsonl.gz` in step_check's `--parts` format (pid = GlobalId, name, desc, solids, faces, valid,
volume), plus `stats.readback_parts`. Validated: forcing the read-back cap to 1 MB on the 10 L2 models gives census
joins identical to step_check's (coverage, matched, volume checked/within/median/p5/p95, surface parts: 10/10) and
identical solid/valid counts; on Camellia the same 162/7735 volume outliers and 37 parts without solid.

**Far mode (opt-in `V6_FAR_VERIFY=1`, ship together with `step_check_far.diff`).** A part beyond 1e7 mm is verified on a
copy of its STEP blocks (own block and shared block) in which every far point (a coordinate >= 1e7 mm; local frames and
the context origin stay) is moved by one model-level whole-km offset. This is exact decimal arithmetic and a rigid
translation, the same rule as the grader patch. Tag `far-origin` in sidecar/stats. The output STEP always keeps the
source coordinates.

## Root causes and results

### A) members not converted (16, all class 3, all reused old-writer STEPs) -> results/members_not_converted.md
- **dev3:** member coverage 0.00-0.47 becomes 1.00 on all 16; 7 class 1, 9 class 2. The fleet has since re-run them
  with 6.1.0-rc, which gives the same levels.
- **Residue 1, far from the origin (OCC precision).** The Baylor Hurd SDS/2 exports sit at x = -1.456e9, y = 3.036e9 mm.
  ulp(3e9 mm) = 4.8e-7 mm, which is above OCC's 1e-7 mm tolerances. The reader's healing throws ("gp_Dir() - input
  vector has zero norm") and BRepCheck reports UnorientableShape / SelfIntersectingWire on solids that are valid.
  Every residual L4 part tested (btp2_M, btp14_M, btp5_M, btp65_8, btp423_1, a122_1, 19.8M2, C_298) reads back valid
  when the same geometry is written 1 km from the origin, and fails in place and as a MAPPED_ITEM placement. A
  tolerance floor rescues only part of them. Verdicts also differ between one-part and whole-file reads, so no
  converter-only representation is OCC-valid; the grader rule is required.
- **Stock grader, far mode off:** class-identical to dev3 on all 15 far models. 14 ran on the final build (vr9).
  ALM_Baylor (d713) ran on vr8, the build before the guarded L2, and matches dev3 exactly: invalid_solids:383,
  L 0:15394/1:103/2:12/4:119. Its far-mode result is also from vr8.
- **With far mode plus the grader rule:** 12 of 15 far models are class 1 (dev3: 7), see the table.
  - 7b35850c and cd3313dc are blocked only by open-surface parts: SDS/2 grating bars and plates given as open shells,
    which is source data and not closable without an owner decision.
  - ALM_Baylor goes from invalid_solids:383 + L4 119 + open-surface 69 (dev3) to L4 15 + open-surface 68, with the STEP
    at 158 MB instead of 358 MB.
- **Corpus:** 51 IFC/DB1 models have |coordinates| >= 1e8 mm (classes 1/2/3 = 5/31/15).
- **Camellia** (not far): class 3 -> class 2. What remains belongs to other items: Tekla DUMMY beams with open
  surfaces, and volume outliers.

### B) per-part verification pending (159: STEP over the 1 GB cap 155, read-back OOM 4) -> results/per_part_pending.md
- **No geometry defect:** there is no per-part STEP data, so there is no census join.
- **dev3 cannot be run on these SDS/2 models as is,** because of the memory runaway (E).
- **dev3+vr output is far smaller** (instancing, coplanar merge). All 4 measured models come in under the cap (decimal
  MB): BOSK_FM 1,389 -> 499, Seaport 1,153 -> 585, Gateway balance-of-plant 1,136 -> 627, Stockton 853 -> 207 (Stockton
  was a read-back OOM case). Under the cap the ordinary read-back gives per-part data, so the issue disappears. Converter
  peak RSS is 0.8-1.8 GB. Those graded stay class 2 on other items: open-surface source shells and L4. BOSK_FM, run on a
  build without G, also shows 6 grader-invalid solids.
- **For STEPs still over the cap,** F plus the worker hook give the join from the converter read-back.
  'per_part_verification_pending' disappears; 'not_read_back_large_file' stays for the step-verify-big job.
- **Residue:** none on the converter side for this item.

### C) valueerror (15, SDS2, not IFC)
- **13 x BG PODIUM_Job** (7.331, z3-sds2-v4): `PLG12x14x300: built-up dimensions match neither name nor weight`.
  Fixed since SDS2 v5 (`_builtup()` never raises); needs only a re-run with v5.3/v5.4.
- **KJL** (7.425, v5.1; 1,812 valid solids were written): the `verify_step.main()` render crashes on an empty triangle
  list (a reference model spread over km). Patch `sds2_v5.4_verify_step_render_guard.diff` draws all items, else skips
  the render (render only). Reviewed, not run (1.1 GB job, SDS2 box).
- **CSU 15-027** (7.312, v5.1): `mem_idx: member work points not found`. v5.4 has the identical `calibrate()` and
  `sparse_layout()`, and the job's mem_idx is 588 MB for about 23.5k members. This is an open SDS2 decoder item; I did
  not patch it blind.

### D) L2-alt-source parts still written by dev3 -> results/l2_evidence.md (18 parts, 5 models)
- **5 solid L2 parts:** each is the triangle mesh of the same IFC item whose polyhedral L0 failed. All read back valid
  in the grader. Volume is within 0.1 % of the exact kernel B-rep and within 0.04 % of the census analytic volume where
  present. Vertices lie within 0.0087 mm (the output grid) of the exact surface. 4 of the 5 are far-origin cases.
- **13 Camellia DUMMY beams:** surface-only L2. The kernel gives about 386 open shells; the exact B-rep is +13 % against
  Tekla's net quantity. This is source geometry, and these parts already carry the blocking open-surface tag.
- **10 L2-heavy models** (6.0.1: 1-48 L2 parts each): dev3 makes all class 1 with 1 L2 part left; dev3+vr leaves 0 L2.

## Patches to the grader / fleet (lead decisions; not applied by me)
- `step_check_far.diff`: a far file (a CARTESIAN_POINT coordinate >= 1e7 mm) is read twice. Roots, products, faces
  and bbox come from the file; BRepCheck and volume per root come from a copy whose far points are moved by one
  whole-km offset (local frames and the origin stay).
  On dev3 outputs of far models the verdict is unchanged (c951cd2d 40/40, d9962a0c 148/148, 7ff7ad6b 350/350 valid,
  bbox identical). It is required for the far-mode class lift.
- `worker_converter_readback.diff`: when the STEP is over the read-back cap and `<out>.verify_parts.jsonl.gz` exists,
  join with the census from it (`per_part_source: converter_readback`).

## Changes vs the preliminary upload (18:11, merged into 6.1.1-rc by the IFC improver)
- **Removed D** (no instancing beyond 1e7 mm, no ghash dedup for far copies). Far mode makes it unnecessary, and it
  showed no measurable gain. I first attributed the 7ff7ad6b regression to D; it reproduces without D and comes from E
  (see E).
- **Replaced the last-resort far round with far mode.** The last-resort round could not rescue far instances whose
  shared geometry is itself far (SDS/2 world-frame maps).
- **Added G** (near-origin instance dedup false passes, Stockton).
- The grader rule is now the second-read form; the earlier whole-file translation also moved #110 and broke the checks.

## Incident (reported to the coordinator at once)
At 01:14Z I overwrote `_control/z3conv/sds2/pybin.txt` with an empty object (a mistyped `aws s3 cp - <key>` meant to be
a read). The coordinator restored it at 01:17:17Z. Since then every write goes through `job/safe_put.sh`, which refuses
destinations outside my own prefixes.

## Reproduce
`job/rc.py` (worker + classifier with the live rules), `job/drive.py LABEL CONVERTER TARGETS.json`, targets in
`job/targets_*.json`. Diagnostics: `job/diag_far.py`, `job/diag_far2.py` (far origin), `job/probe_kernel.py`,
`job/probe_iter.py`, `job/variant_test.py` (memory runaway), `job/l2ev.py` (L2 evidence). Results live under
s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/<label>/.
