# Adversarial review: ifc-volume-residue

**Verdict: REFUTED as "ready".** Converter patch 1 (`ifc2step6-dev3_opening-contact-walls.diff`) loses real parts and turns valid
solids into open-surface stand-ins on other SDS/2 models. That contradicts the deliverable's "no part lost, no other part changed"
regression claim. Patch 1 has also already been merged unchanged (same `bad1 < bad0` guard) into **ifc2step6 6.1.2-dev**
(`agentjobs/ifcv6/ifc2step6_612dev.py`, lines 3019-3022 / 3350). Patch 2 (null curve segments) and the census v3 proposal hold up.
Patch 1 helps on the 36-face countersunk-hole case and should be kept **only with a safe guard** (section 5).

Everything below ran on BOX-A (i-0c694360a18d7759f), `/work/agentwork/ifc-volume-residue-review`, through the fleet worker's own
`process()` plus `build_index.classify_ifc()` with live `rules.json` (`review/scripts/run_case3.py`, `batch3.py`). Converters: dev3
(md5 f23651e8..., the base) and dev3 + patch 1 + patch 2 (md5 758c9247..., the same as the deliverable's combined file). Results:
`s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue-review/` (local copy
`review/res2/`). Scripts: `review/scripts/` (also under `s3://annotationprod/.../agentjobs/ifc-volume-residue-review/`).
The Mac only ran gid-joins of small JSON files.

## 1. Re-run of the deliverable's own before/after (R set, 7 models x 3 configs): CONFIRMED

| model | dev3 | dev3+p1+p2 | dev3+p1+p2 + census v3 |
|---|---|---|---|
| aa33931d26f7b00f | 2, cov 0.983 | **1**, cov 1.0 (+1 plate 2P1525) | 1 |
| 224b42bfc48cf6d2 | 2, cov 0.9808 | 2, cov 1.0 (+28 plates) | 2 (pws 7) |
| e5f30a12ecc5f3e5 | 2, 353/8297 outside, cov 0.9997 | 2, 353/8299, cov 1.0 (+2 SHEAR TAB) | **1** |
| 3a5129c14f17f9b0 | 2, 227/904 | 2, 227/904 | **1** |
| 0a2c43d06678a61b | 2, 79/11198 | 2, 79/11198 | **1** |
| f356b275dd5993f2 | 2, 188/12434 | 2, 188/12434 | **1** |
| 03af2c3170d9a570 | 2, 81/6567 | 2, 81/6567 | 2, 2/6567 (the 2 kernel boolean failures) |

The numbers match the README exactly. Gid-join dev3 -> patched: 31 new parts, 0 lost, 0 volume changes. All recovered parts are
level-0 valid solids. Their volume agrees within 0.3 % with an independent OCC check, built as body without openings minus
common(body, fused repaired openings) (`recov.py`). The 2 SHEAR TABs come out at 3 834 573 mm3, exactly the closed polyline area
times the depth. So for these 7 models the deliverable is correct.

## 2. Patch 1 on DIFFERENT real models: REGRESSION (lost parts, solids degraded to open surfaces)

Probe (`probe.py`, parse-only, the patched converter's own `repair_opening_shells`) over **2 932 IFC sources** of the pool:
patch 1 fires in **28 models** (330 shells, 1 119 products). In **11 of them, 231 of the 330 'repaired' shells are still not
2-manifold after the repair** (bad1 > 0). Those are the 30- to 164-face opening shells of SDS/2 v2020 pipe members ('pp...'),
not the 36-face countersink. So the README / docstring claim "only when that makes it 2-manifold where it was not" is **false
for the code**: the guard is `bad1 < bad0`.

D set = 23 different models (10 live class-1 controls, 12 patch-1 triggers, 1 patch-2 trigger), dev3 vs dev3+p1+p2. E set = 4 more
patch-1 triggers (2 clean, 2 partial). STEP parts gid-joined with `review/scripts/cmp_parts.py`:

| model (SDS/2 v2020) | dev3 class / cov / pws | patched class / cov / pws | lost parts | valid solid -> open-surface | gained |
|---|---|---|---|---|---|
| 7ec85dca81b918c9 | 2 / 1.0 / 12 | 2 / **0.9516** / 18 | **9** (pp11017, pp11398 x4, pp11410 x2, pp11418, pp11424) | **6** | 0 |
| 1ea774eb6201c3e1 | 2 / 1.0 / 8 | 2 / **0.9657** / 16 | **9** (pp10326, pp10373 x4, pp11100 x2, pp11145 x2) | **8** | 0 |
| df6df9298ccdbed4 | 2 / 0.9718 / 1 | 2 / 1.0 / 13 | 0 | **13** (2PP988 x13) | 83 |
| e1828d1ce27d5aca | 2 / 0.9818 / 1 | 2 / 0.9818 / 5 | 0 | **4** (pp10256, pp11117, pp11902 x2) | 0 |
| c8f3e1a6c10b3496 (E set) | 2 / 0.9994 / 42 | 2 / **0.9899** / 71 | **18** (pp10373, pp10916, pp11290, pp11434, pp12649) | **29** | 1 |
| **total, 5 models** | | | **36 lost** (16.9e6 mm3, all valid level-0 solids in dev3) | **60** | 84 |

Converter stats agree: `parts_without_geometry` 0 -> 9 (7ec85, 1ea77), 1 -> 18 (c8f3); `surface_fallback_parts` 12 -> 18, 8 -> 16,
1 -> 13, 1 -> 5, 42 -> 71.

Mechanism, checked at kernel level (`mech.py`: `create_shape` of each affected product on the original file, then again after
the patch's own in-memory `repair_opening_shells`):
* df6df: all 13 products are valid 1-solid B-reps before (40 424.9 mm3 each). After the repair they are **0 solids, 0 polyhedral
  faces**. Their opening shells (30 faces) go from 10 to 5 bad edges: the shells are still non-manifold, but the boolean now
  returns empty.
* e1828: all 4 products are valid before and empty after. pp10256's opening shell (147 faces) becomes edge-2-manifold (6 -> 0)
  and the boolean **still** returns empty.
* No repaired shell is shared with a non-opening product. The product bodies themselves are untouched. The damage comes only
  from the modified tool: dev3's kernel cut these products correctly with the ORIGINAL non-manifold tool. The patch's premise
  ("non-manifold tool -> boolean returns nothing") is not general, and on these models the patch causes exactly the failure it
  was meant to fix.
* 1ea77: all 17 affected products (the 9 lost + 8 degraded, pp10326 / pp10373 / pp11100 / pp11145 / pp11084 / pp14971) are
  valid 1-solid B-reps before (193 522 to 543 399 mm3) and **empty** after. Their opening shells (146-164 faces) go 9 -> 4,
  26 -> 14, 28 -> 20 bad edges.
* 7ec85: all 15 affected products are valid before (172 488 to 651 339 mm3) and empty after. That includes pp11547, whose two
  146-face opening shells become edge-2-manifold (5 -> 0 bad edges).
* In total, **49 of 49** products (the 18 lost + 31 degraded of the D set) build as valid solids from the original file and as
  nothing after the patch's repair. The opening bodies are not valid OCC solids either before or after.

Strict-guard variant (`review/scripts/strict_variant.diff`: repair only if `bad1 == 0 and bad0 > 0`), same 9 trigger models:
no lost parts and every 36-face gain kept (aa33, 224b, 8602, 1d42: identical gains). It still degrades **3** valid solids to
open-surface (7ec85 x2, e1828 pp10256), and df6df gains only 15 of the 83. **An edge-count guard alone is not safe.**

Positive side, same runs (all from the 36-face countersink shell, bad1 = 0): 9 more models reach class 1 that the deliverable
did not test. They are 1d42caf4398a55b7 (3 -> 1), 860211137cefec8f, 79814460e4995ade, 7e4eb04480fd465c, f139b59153637970,
c66905b74909eef0, bf4eb0513052a84a, 5502b35f4feac183, 40e1f70c0b271232 (2 -> 1 each). Together they recover 47 plates (the D-set ones checked with `recov.py`:
S/E 0.997-0.9999, all valid). cc2895696435834b (1 partial + 1 clean shell): +1 part, no regression. 39456674690989ee: 1 member
(ts2304) whose opening dev3 did not cut is now cut (S = E within 0.01 %). Class-1 controls (10): no lost parts, no changed
part, no class change.

## 3. Patch 2 (null composite-curve segments): CONFIRMED, with one caveat

* Probe over 2 932 sources: exactly 2 models contain `IfcCompositeCurveSegment(..., #0)`: e5f30a12ecc5f3e5 (the deliverable's
  case) and **56917a7700b770e4** (Tekla 2017i SP7, a different model). In both, the remaining segment is a closed polyline.
  56917: +2 parts, coverage 0.9995 -> 1.0, 0 lost, 0 changed. Everywhere else it is a no-op (`null_curve_segments_dropped` 0).
* Caveat (synthetic, `synth_p2.py`): if the remaining segments did NOT close, then after the drop the kernel closes the profile
  with a chord. It returns 3 641 025 mm3, an invented edge, instead of failing. No such file exists in the corpus. A one-line
  guard ('apply only if the kept segments chain end to start') would make it fabrication-proof.

## 4. Census v3 (grader proposal): CONFIRMED on the sample and on live class-1 rows

Note: the kit's `s3://annotationprod/.../z3conv/ifc/ifc_census.py` was replaced at 2026-10-02T02:54Z and is **already
census v3**. Reverse-applying the deliverable's diff gives back the v2 file (md5 58f0d49d...). So this is live, not 'not
deployed'.

* Truth check (`truth.py`, R_comb3): every part census v3 clears that v2 flagged (79 in 03af, 227 in 3a51, 300 of 353 sampled
  in e5f3) has STEP = exact kernel B-rep (within 1 % / 3 % curved). So v3 does not hide any converter deviation there. v3 makes
  no new outside parts.
* Tekla sharp-profile basis: after rescale, STEP/q is within 0.5 % for 285/300, 1395/1414, 479/483, 777/784 cut parts (03af,
  e5f3, 0a2c, f356). Before rescale, 0 parts are within 0.5 %. The hypothesis is right on these exporters.
* Census v2 vs v3 on the **live STEP of 713 live rows** (652 class 1, 61 class 2; `census_cmp.py`): 6 467 parts get a new
  analytic value, 0 of them outside. The total outside goes from 3 846 to 2 902. There is 1 new outside part (an open-surface
  'DUMMY' Tekla 16.1 beam, already a stand-in, in a class-2 row). On class-1 rows, v3 adds outside parts in **one** row,
  09f466032521b8c5 (0/50 -> 5/91). Checked (`insp_an.py`): the new v3 expectation equals the exact kernel volume (ratio 1.0000)
  and the old reused v5 STEP holds 1.46x volume for 5 IfcBuildingElementProxy (8886 / 8882, profile with voids, voids not cut).
  So v3 exposes a real defect of a live class-1 row; that is correct behaviour, not a census bug.
* Side note for the reconversion plan: live class-1 control 81f9b1a645863620 (Tekla 2018i, Brep bodies) comes out **class 2**
  under dev3 + census v2 (gid join: 18 W beams at 1.08 'net'). Census v3 cannot rescale Brep bodies (no profile parameters).
  This is the same Tekla sharp-basis effect, so do not mass-reconvert class-1 Tekla rows on the strength of this item.

## 5. What must change before 'ready'

1. **Patch 1: replace the up-front repair with a retry.** Run the kernel pass unchanged. For kernel products that come back
   EMPTY (`parts_without_geometry`) and have an opening shell with contact-wall pairs, rebuild only those products with the
   repaired shells. Products that already convert can then not change, by construction. Re-test on 7ec85dca81b918c9,
   1ea774eb6201c3e1, df6df9298ccdbed4, e1828d1ce27d5aca (regressions) and aa33 / 224b / bf4e / 5502 (gains). If the retry path
   is not wanted, at least limit the repair to shells where `bad1 == 0` and the product's first kernel result is empty.
2. **Pull patch 1 back out of ifc2step6 6.1.2-dev** (or switch it to the retry form) before 6.1.2 is used for reconversion. As
   merged now, it puts at risk the 11 partial-repair models of the pool. 6 were measured here: 7ec85, 1ea77, df6df, e1828 and
   c8f3 regress; cc28 does not. Not measured: c3fb96fbca5e26e8, 442b41810f444096, 09e646c20e3f5c79, 2c9b63bcc70e12be,
   7eab47c29ac466c9.
3. Fix the README / docstring wording ("only when that makes it 2-manifold") and the regression claim. The 36-model sample had
   no 146-164-face pipe-cope shells, so it could not see this.
4. Patch 2: add the closure guard (optional; no corpus file needs it).

## 6. Additional runs (job 5) and bookkeeping

* E set (4 more different SDS/2 v2020 patch-1 triggers): 5502b35f4feac183 2 -> **1** (+4 plates), 40e1f70c0b271232 2 -> **1**
  (+5), cc2895696435834b (1 partial + 1 clean shell): +1 part and no regression, **c8f3e1a6c10b3496 (27 partial shells):
  18 parts lost, 29 solids -> open-surface, coverage 0.9994 -> 0.9899** (the table row in section 2).
* Overall patch-1 balance over the 34 models run here (23 D + 4 E + 7 R): +161 recovered parts and 10 models lifted to class 1
  (9 of them outside the author's sample), **but 36 parts lost and 60 valid solids degraded** in 5 models. The losses come from the partial-repair shells,
  which occur in 11 of the 28 trigger models in the pool. A converter change that loses valid solids cannot ship as is.
* Patch 2 and census v3: no regression found (sections 3, 4).
* Root causes A-F, H-K (attribution, census story): consistent with everything re-run here; not contested.
* Deliverable files: base md5 f23651e819ec959abb0619fc4a3ae9d0 verified. Both diffs apply to dev3, dev4, 6.1.0-rc and
  6.1.1-dev. Patch 1 does NOT apply to 6.1.1-rc / 6.1.2-dev, because 6.1.2-dev already contains it. S3 uploads are
  byte-identical to the local files.
* Live counts drift: the 2026-10-02T01:31Z live index snapshot holds 138 rows (131 ifc + 7 db1) with a volume-tolerance issue,
  not 178 + 13. The fleet is moving; the README's per-model numbers were re-verified only for the 7 R models.
* BOX-A: reviewer workdir cleaned (6.7 MB left: logs + scripts). No instances launched, nothing published; only my own PIDs
  were killed (my duplicated mech runs).

Evidence index (all under `.../agentwork/ifc-volume-residue-review/`): `R_dev3|R_comb|R_comb3/<id>/` (re-run),
`D_dev3|D_comb|S_strict|E_dev3|E_comb/<id>/` (case.json, out.step.stats.json, step_parts.jsonl.gz, src_parts.jsonl.gz),
`probe.jsonl` (2 932 sources), `recov/*.json` (independent volume of new / changed parts), `mech/*.json` (kernel before / after
repair), `truth/*.json` (census v3 cleared parts vs exact B-rep), `census_cmp.jsonl` (713 live rows, v2 vs v3),
`insp/09f466032521b8c5.json`.
