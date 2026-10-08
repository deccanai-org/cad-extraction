# pfix ifc-verification-residue (pipeline ifc, BOX-A) - patches against ifc2step6 6.1.0-dev3

Items: 'ifc per-part verification' (159 models in the 00:06Z plan), 'ifc members not converted' (16), 'valueerror'
(15; these turned out to be SDS2-pipeline rows, see section 5). Evidence on L2-alt-source parts is in section 4.
Everything ran on BOX-A under /work/agentwork/ifc-verification-residue (results:
s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/<label>/).
Harness: `job/rc.py` = the fleet's own worker.process (conversion ladder, step_check, ifc_census, grade_join) with the
converter swapped, then the coordinator's classify_ifc with the live rules.json. No geometry is added anywhere.

## 0. URGENT: dev3 / 6.1.0-rc can run away in memory (patch E)

dev3 sends faceted products with openings to the kernel in polyhedral mode (POLYHEDRON_WITH_HOLES). On data-3 Seaport L4
(beeeacea7d2d, an 18 MB zip from SDS/2) the dev3 converter reached **173 GB RSS** within ~10 min of the kernel pass, and I
killed it. Bisected to a single product, **a3717** (IfcMember L2x2x3/8, eid 8935, GlobalId 02dnNiHvr9xext7h6RlJ8V: a 12-face
IfcFacetedBrep minus two 18-face faceted hole prisms):

| kernel setting (one create_shape, child capped at 12 GB) | result |
|---|---|
| polyhedral (dev3) | exceeds 12 GB -> RuntimeError (bad_alloc) |
| polyhedral, boolean-attempt-2d off / weld off | same |
| **triangle mesh** | **0.14 s, 172 triangles, 1 valid solid, 343,261 mm3** |
| polyhedral, openings disabled (reference only) | 0.04 s, 352,670 mm3 |

With 500-product iterator chunks memory stayed at ~1 GB until the iterator reached this product; a3717 itself still blew
up (48.8 GB at the watchdog kill), so chunking is not the fix. **Patch E:** in `kernel_run`, products with openings are meshed as
triangles; the rest keep polyhedral output. dev3's `merge_coplanar` turns coplanar triangles back into the same planar
polygons with holes: it is exact (no vertex moves, no surface changes), and the STEP sizes below confirm it. Opting out:
`V6_OPENINGS_POLY=1`. Opening products took 1-7 s each in polyhedral mode and 0.1-0.2 s as triangles.
Seaport with dev3+vr: the kernel pass ran at a flat **1.28 GB** for its first 14+ min (still running at the time of
writing).
Repro: `patch/repro_seaport.sh single` (about 1 min, capped) or `... full`.

## 1. Patches (all in `patch/ifc2step6_dev3_verification-residue.diff`, full file `ifc2step6_dev3+vr.py`)

| | change | why / evidence |
|---|---|---|
| A | MAPPED_ITEM placement point written as fixed-point, 6 decimals (`_rp`) | `_r` (%.10g) keeps only 10 significant digits: an instance 3e9 mm from the origin was placed to the nearest mm, and 2e8 mm to 0.1 mm |
| D | far from the origin (> `V6_FAR_MM`, default 1e7 mm): no MAPPED_ITEM instancing and no translation-invariant verify dedup | there OCC's verdict depends on the absolute position, so one verified copy does not stand for the others. 944bc6d8: the L2 part becomes L0 |
| E | products with openings meshed as triangles in the kernel pass | section 0 |
| F | `<out>.verify_parts.jsonl.gz`: the read-back record of every written part, in step_check's `--parts` format (pid = GlobalId), plus `stats.readback_parts` totals | gives per-part data for STEPs over the 1 GB whole-file cap (section 3) |
| B' | **opt-in** `V6_FAR_VERIFY=1`: a far part that fails every in-place level is re-verified on a copy of its own block, shifted by whole km (exact decimal), and kept as the exact L0 solid (tag `far-origin`) | section 2. Ship **only together with** `step_check_far.diff`: with the stock grader those solids read as invalid |

Other files:
- `step_check_far.diff` (grader, vs the live ifc/step_check.py): for a far file without MAPPED_ITEM, the OCC read uses a
  copy whose 3D geometry points (the (0,0,0) context origin excluded) are all shifted by the same whole km, in exact
  decimal arithmetic. The bbox is reported in file coordinates (checked: equal to the stock bbox).
- `worker_converter_readback.diff` (fleet worker, vs the live ifc/worker.py): when the STEP is over RB_MAX and
  `verify_parts.jsonl.gz` exists, join from it and record `validate.per_part_source = converter_readback`.
- `build_index_converter_readback.proposal.diff` (coordinator classifier, **proposal**; it changes a grading rule, so the
  lead decides): `graded_by = converter_readback`, with the issues taken from the converter's per-part totals instead of
  `not_read_back_large_file`.
- `sds2_v5.4_verify_step_render_guard.diff` (SDS2 v5.4, section 5).

## 2. 'ifc members not converted' (16 class-3 rows)

Root cause: all 16 were **reused disk-1/2 STEPs from an older writer** (no GlobalId as PRODUCT.id), so the join fell
back to part names and found 0-47 % of the members. A dev3 re-run (gid join) gives **member coverage 1.0 on all 16; none
remains class 3.** The fleet has meanwhile re-run 14 of them with 6.1.0-rc (00:49-00:54Z, same levels as dev3) and 4f6b8e2e with 6.0.1.

| model | index 00:06Z | dev3 | dev3+vr (stock grader) | dev3+vr + V6_FAR_VERIFY=1 + step_check_far |
|---|---|---|---|---|
| c951cd2d377d | 3 cov 0.22 | **1** | 1 | 1 |
| b79c4f3a9377 | 3 cov 0.20 | **1** | | |
| d9962a0cdfd3 | 3 cov 0.17 | **1** | 1 | 1 |
| 708137998946 | 3 cov 0.27 | **1** | | |
| e43ef5137745 | 3 cov 0.34 | **1** | | |
| 944bc6d8f919 | 3 cov 0.33 | **1** (1 L2) | 1 (L2 -> L0) | 1 |
| 7ff7ad6bbfd8 | 3 cov 0.38 | **1** | | |
| c13135ba64e2 | 3 cov 0.00 | 2 L4-surface:6 | 2 L4:6 | **1** |
| 4f6b8e2e9693 | 3 cov 0.01 | 2 L4-surface:4 | 2 L4:4 | **1** |
| 700b4c5c15d6 | 3 cov 0.39 | 2 L4-surface:1 | 2 L4:1 | **1** |
| 6f3ceef9bdcb | 3 cov 0.38 | 2 L4-surface:2 | 2 L4:2 | **1** |
| 7b35850cd279 | 3 cov 0.37 | 2 L4:1, open-surface:14 | same | 2 open-surface:14 |
| 925e43c7b39a | 3 cov 0.35 | 2 open-surface:4 | | |
| cd3313dc0284 | 3 cov 0.47 | 2 open-surface:17 | | |
| 4bbcc615d753 | 3 cov 0.00 | 2 open-surface:47, vol 162/7735, no-solid 37 | | |
| d713eae4bf9d | 3 cov 0.44 | 2 invalid 383, L4-surface:119, open-surface:69 | running | running |

**Far-origin root cause (the L4s of the Baylor Hurd models).** These models sit at x = -1.456e9 mm, y = 3.036e9 mm
(geo-referenced SDS/2). The parts are valid solids, but OCC's 1e-7 mm tolerances are finer than the coordinates'
floating-point step (ulp(3e9 mm) = 4.8e-7 mm), so the reader's FixShape throws ("gp_Dir() - input vector has zero
norm"). BRepCheck then reports UnorientableShape / SelfIntersectingWire for every face. Measured per part (`job/diag_far.py`,
`diag_far2.py`):

| part | in place | translated by whole km (exact) | MAPPED_ITEM translation | tolerance floor 8 ulp |
|---|---|---|---|---|
| btp2_M 0Dcno5GC10KvAeo5hL2xEF (kernel poly / tri) | invalid (12 F unorientable) | **valid**, vol equal | invalid | valid |
| btp14_M, 19.8M2, C_298 | invalid | **valid** | invalid | valid (C_298) |
| btp5_M, btp6_M (with openings) | invalid (+6 self-intersecting wires) | **valid** | | invalid |
| btp65_8 (transcoded), a122_1, btp423_1 | invalid | **valid** | invalid | invalid |

So in place no representation passes, and every L1/L2/L4 fallback on these parts is a precision artefact. The surface
fallback even drops a valid exact solid. B' plus `step_check_far` keeps the exact solid and grades it on the translated
copy. **Owner/lead decision**: a CAD consumer reading these files in place with OCC sees the same BRepCheck failures.
The alternative would move the model's coordinates (a site offset), which the owner rule forbids. Grader check of
`step_check_far` on stock outputs: identical counts on files where everything was valid (c13135, d9962a, c951 untouched,
since it is not far) and identical bboxes. On B' outputs: c13135 62/62 valid (stock 56/62), 4f6b8e 158/158 (stock 154/158).

Remaining class-2 causes (not converter-fixable without invented geometry, or owner decisions):
- `open-surface` = zero-thickness double-sided source surfaces (gt12/gt14 grating bars, M_491 / 40.6M2 plates, bolt
  heads in 925e). The source holds no solid; closing them would be added geometry (owner rule).
- 4bbcc615 Camellia (Tekla): 37 IfcBeam "DUMMY" parts, IfcBooleanClippingResult. The kernel facets come out as 256-396
  disconnected open shells per part. The exact OCC B-rep of the same item exists (2.15e6 mm3, vertices within 0.007 mm),
  while the census net quantity is 1.90e6 (12 % lower). The 162 volume outliers are the same family. Follow-up candidate:
  mesh the exact B-rep with BRepMesh and sew it (source geometry, no invention); not done here.

## 3. 'ifc per-part verification' (159)

Root cause: STEP > 1 GB (155) or a read-back memory kill (4), so no per-part step_check records and no join. The
converter already reads **every part back** in its own small STEP block with step_check's checks, but threw the records
away. Patch F keeps them, the worker hook joins from them, and the proposal lets the classifier accept them.

Validation on the 10 L2 models with `RB_MAX_MB=1` (forces the over-cap path): the join from the converter read-back is
**identical in 10/10** to the join from the full step_check (coverage, matched, volume checked / within / outside /
median / p5 / p95, surface parts), and the solids / valid / non-positive counts are identical. Classifier: stock gives
class 2 `not_read_back_large_file` on 9; with the proposal diff those 9 are class 1 again (graded_by converter_readback).
The 10th is under the cap and unchanged.
Caveat: parts with identical geometry up to translation are verified once and the result copied (dev3 behaviour; D
turns this off for far parts). MAPPED_ITEM parts are verified with their shared block.

Re-run status of the 159: I did not re-run all of them (72 GB of input; the 500 MB-1.2 GB Gateway SDS/2 models take
30+ min each). The fleet's jobs_reconvert.json already holds 81 of them for 6.1.0-rc, and those runs have the patch-E
memory risk. Run on BOX-A with dev3+vr (`ppv_vr3`, `ppv_vr4b`; progress.json under the agentwork prefix):
Seaport (beeeacea, the blow-up case), BOSK_FM (1c61df42; L0 verify 27,223 parts, 66 failed), Stockton (2c0f7a89,
read-back OOM before), Gateway BoP (af3c44bd, 1080 L2 under 6.0.1), queued: 2bcaa301, e21b8fa4, be39310e, 1924e526,
54af551c, d3316ea5, 313402b4. Results land in `<label>/progress.json` as they finish.

## 4. L2-alt-source evidence (dev3), `l2ev/*.jsonl`

L2 count: the 10 models that had 16-48 L2 parts each under 6.0.1 (300 in total) have **1 L2 part under dev3** (e4901c30)
and **0 under dev3+vr**; all 10 are class 1 with both. STEP size is within 0.1 MB and runtime about the same:

| model | 6.0.1 L2 | dev3 class / levels / MB / s | dev3+vr class / levels / MB / s |
|---|---|---|---|
| e4901c30087b | 41 | 1 / L0:1057 L2:1 / 11.8 / 65.6 | 1 / L0:1058 / 12.3 / 59.3 |
| 749c9cd1eb18 | 31 | 1 / L0:237 / 3.1 / 21.3 | 1 / L0:237 / 3.1 / 16.5 |
| 3a7da4ce6b6a | 35 | 1 / L0:143 / 6.5 / 49.5 | 1 / L0:143 / 6.5 / 47.9 |
| 0e11be1f337e | 48 | 1 / L0:823 / 3.6 / 24.2 | 1 / L0:823 / 3.6 / 19.5 |
| 75d22c70b24f | 38 | 1 / L0:566 / 6.2 / 40.5 | 1 / L0:566 / 6.3 / 33.2 |
| a901254aae2a | 16 | 1 / L0:124 / 1.0 / 8.5 | 1 / L0:124 / 0.9 / 10.5 |
| 90263e4576c8 | 16 | 1 / L0:318 / 3.3 / 16.4 | 1 / L0:318 / 3.3 / 20.6 |
| 0e047d170568 | 30 | 1 / L0:670 / 5.3 / 44.2 | 1 / L0:670 / 5.3 / 40.9 |
| 042c7d952655 | 24 | 1 / L0:394 / 6.1 / 37.8 | 1 / L0:394 / 6.1 / 41.0 |
| 37aebdc71e2a | 21 | 1 / L0:311 / 5.7 / 34.1 | 1 / L0:311 / 5.7 / 36.3 |

The 18 L2 parts that dev3 still writes (5 models), measured from the produced STEP (`job/l2ev.py`: grader step_check
record, independent OCC re-read, exact kernel B-rep of the same IFC product, census):
- **Same source item: yes, all 18.** The L2 representation is the kernel output of the same body representation item(s)
  of the same product (MappedItem -> IfcExtrudedAreaSolid / IfcBooleanClippingResult / IfcFacetedBrep). Only the
  faceting route changes (polyhedral -> triangles, or transcoder -> kernel).
- **5 solid L2 parts: valid** (grader and re-read: 1/1 valid, vertices within 0.0053-0.008 mm of the exact B-rep):
  btp14_M 20pMG6xcT4PxReeWzIKuVz census 1.0004 / exact 1.000396; btp423_1 2_TkAlvfbCmvMQlufSg7JC and
  2IOG6SJaH3APqo0quDZxsM census 1.0003; 15.8S1L1 2jUowy0er52ge1D09iB2zb exact 1.000347 (no census volume);
  1C1646 3ZWBMkK69Ayv0rhigAiZqh (faceted brep source, open in source) exact 0.998986.
  Four of the five are far-origin parts (section 2): with D they pass at L0 (944bc6d8), or they still reach L2 through
  the in-place precision issue.
- **13 L2 parts in 4bbcc615 are surfaces** (L2 + open-surface, 0 solids): the "DUMMY" beams of section 2, vertices
  within 0.0064-0.0081 mm of the exact B-rep, no solid to check against the census.

## 5. 'valueerror' (15 rows): SDS2 pipeline, not IFC

- 13 x Boston Garden BG PODIUM (SDS/2 7.331) on code v4: `PLG12x14x300: built-up dimensions match neither name nor weight`.
  This was **fixed in SDS2 v5** (CHANGES item 2: `_builtup()` never raises). They need a re-run with v5.4. The
  reconvert.json sds2 class-3 rule should pick them up; the results I read at 00:12Z were still the v4 runs.
- f3e696bf KJL 7.425 on v5.1: crash in `verify_step` while rendering. Reference model spread over 25 km: no item lies
  within 6000 in of the median centre, so the triangle list is empty and `.min()` fails. The STEP itself was written
  (1812 solids, all valid). `sds2_v5.4_verify_step_render_guard.diff` (vs v5.4): fall back to all items, otherwise skip
  the render. Static fix; not run on a job (SDS2 runs belong on BOX-C).
- 347cb74f 15-027 CSU 7.312 on v5.1: `mem_idx: member work points not found` (calibrate). Still raised in v5.4; it is
  SDS2 decoder work for the SDS2 fixer, so no patch here.

## 6. Files

patch/: `ifc2step6_dev3_verification-residue.diff`, `ifc2step6_dev3+vr.py`, `step_check_far.diff`,
`worker_converter_readback.diff`, `build_index_converter_readback.proposal.diff`, `sds2_v5.4_verify_step_render_guard.diff`,
`repro_seaport.sh`. job/: rc.py, drive.py (harness), diag_far.py, diag_far2.py (far-origin), probe_kernel.py,
probe_iter.py, variant_test.py (kernel memory), l2ev.py (L2 evidence), inspect_prod.py.
Env switches: V6_OPENINGS_POLY=1 (undo E), V6_FAR_MM (D/B' threshold), V6_FAR_VERIFY=1 (B').
