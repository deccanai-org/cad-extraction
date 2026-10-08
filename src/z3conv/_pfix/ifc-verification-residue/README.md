# pfix ifc-verification-residue (pipeline ifc; base ifc2step6 6.1.0-dev3; BOX-A, SDS2 checks on BOX-C)

Item: 'ifc per-part verification' pending, 'ifc members not converted', 'valueerror', and evidence on L2-alt-source
parts. Sessions 1-2 (01-02:13Z) wrote the dev3 patch (A, E, F, G, far mode) and the grader / worker proposals; the fleet has
since merged most of it. Session 3 (02:50-05:05Z, this update) re-ran the affected models with the CURRENT fleet stack
(ifc2step6 6.1.2 + fleet kit + coordinator `build_index` / `rules.json`), found what is still lost, and fixed it.
Nothing was published; every run wrote only under `agentwork/ifc-verification-residue/<label>/`. No geometry is added.

## Status of the three counters (live index 03:09Z)

| counter | now | what it is | where it is fixed |
|---|---|---|---|
| ifc per-part verification | 152 (140 at 04:1xZ, the fleet is re-running them) | STEP over the 1 GB read-back cap (151) or read-back OOM (1); 150 are reused / ifc2step5 / 6.0.x STEPs, 2 are 6.1 outputs | all of them are on the coordinator's 6.1.2 re-convert list; the fleet worker now reads over-cap STEPs with `step_verify_big` and falls back to the converter's per-part read-back (patch F; `verified_by_converter_readback`, never class 1, lead 02:05Z). No converter defect left (sample below). |
| ifc members not converted | 0 | the 16 Baylor Hurd / Camellia / ALM rows were re-run by the fleet with 6.1.0 / 6.1: 5 class 1, 11 class 2 (6.1.2 makes it 10 of the 14 Baylor files, section 2) | the far-origin part of the residue: **section 2** (+2 class 1 of 14, exact L0 for 31 L1 parts) |
| valueerror | 15 (SDS2; 16 at 03:4xZ) | 13 BG PODIUM / Boston Garden = v4 runs; 15-027 CSU (v5.4.1); 100_Binney_Slab_Job (v5.5.0, again on v5.5.3); new: Boylston_Job 7.221 (v5.5.3) | Binney Slab + Boylston: **section 1** (patch); BG: re-run (v5.5.3 check run on BOX-C, section 1); CSU: sds2-weights-failures work tree (not in v5.5.3) |

What the fleet already runs from this slug: ifc2step6 6.1.1 / 6.1.2 = A (placement precision), E (triangle mesh for products
with openings, memory run-away), F (`<out>.verify_parts.jsonl.gz`), G (every instance read back where it sits) and the
*preliminary* far round; worker = svb + converter read-back fallback; `step_check` = the *first* far rule (whole-file
translation, skipped for files that contain MAPPED_ITEM).

## Files (s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/pfix/ifc-verification-residue/)

| file | base | what |
|---|---|---|
| `ifc2step6_dev3_verification-residue.diff`, `ifc2step6_dev3+vr.py` | dev3 (md5 f23651e8) | the converter patch (A, E, F, G, far mode), unchanged since 19:12 local |
| **`ifc2step6_6.1.2_far_always.diff`**, `ifc2step6_6.1.2+farall.py` | fleet 6.1.2 (md5 4d7476e4; applies to 6.1.3-dev too) | NEW: dev3+vr far mode ported to 6.1.2, opt-in `V6_FAR_ALWAYS=1`; off = byte-identical behaviour |
| **`step_check_far_secondread_vs_fleet.diff`** | fleet `step_check.py` (md5 3f26ca81) | NEW: the second-read far rule against the fleet's current step_check (also MAPPED_ITEM files; keeps the `far_points` / `translated_for_check_mm` keys the coordinator reads). Sequential: the translated copy is read and checked first and released before the file is read (`grader/step_check_far_secondread_concurrent_vs_fleet.diff` = the variant used in the matrix runs; identical output on 6 STEPs, see section 2) |
| `step_check_far.diff` | kit step_check (md5 1ce65a3c) | the same second-read rule against the older kit (as uploaded 19:13 local) |
| **`sds2_v5.4_sparse_layout_7243.diff`** | sds2-step-pipeline v5.4 (applies to v5.5.3) | NEW: 2,494-B slot layout for 7.221 / 7.233 / 7.243 / 7.253 in `sds2job._sparse_try` |
| `sds2_v5.4_verify_step_render_guard.diff` | v5.4 | KJL render guard (KJL itself is fixed in v5.4.1) |
| `worker_converter_readback.diff`, `build_index_converter_readback.proposal.diff` | fleet worker / coordinator | superseded: the lead's 02:05Z rule (svb first, converter read-back only as fallback, never class 1) is in the fleet worker |
| `results/*.md`, `results/l2_evidence*/` | | tables and per-part evidence records |
| `tools/` | | harness (`drive2.py`, `rc2.py` = drive/rc adapted to the 6.1.2 worker's `fl.run(mem_max=)`), `port_far.py`, SDS2 `diag_mem.py`, `calsurvey.py` |

## 1. valueerror (SDS2): 2,494-B mem_idx layout for 7.22x-7.25x jobs without work points (NEW patch)

`100_Binney_Slab_Job` (a47a13079296, live: class 3 `valueerror`, v5.5.0) fails with `mem_idx: member work points not found`.
Two more jobs of the same project fail at the same place but are recorded as `no_member_records_read`:
`100_Binney_Slab_Job` 58c969614e6f (`too few members to calibrate (2)`) and `100_Binney_Slab_Arch_Job` 6eeedc274302.
Root cause (BOX-C, the jobs' own files): they are SDS/2 7.243 jobs whose members are all MISC (2-3 members). `calibrate()`
needs several type markers and a work-point key match; MISC-only jobs have neither, and `sparse_layout()` has a fixed
layout for 2,494-byte slots only for 7.245, so the ValueError is re-raised. The 7.243 layout is the one documented in the
`sds2job` docstring (from 50_Binney): slot 2494, type 0x988, p1 0x112, p2 0x172, section 0x1D4, roll 0x1DA. Survey:
`calibrate()` finds exactly this layout on all 8 data-3 7.243 jobs that have structural members (7 Cives Binney jobs and
Northside_job of another fabricator; 40 to 6,113 members; beam/column sections mapped 27/27 ... 5,776/5,776). The patch adds
that layout to `_sparse_try`; `_sparse_try` still validates it (typed members, finite points, real section entries)
before use. The same failure hit a new row at 03:4xZ, Boylston_Job (5eed44fe33ca, the only data-3 7.221 job, a seed job:
5,127 member files of 140 bytes with a zero work point). Its own mem_idx holds the same layout (type markers 5,127 / 5,127 at
0x988; calibrate()'s own section search with these point offsets picks 0x1D4: 3,000 / 3,000 beams on 152 real sections, the
next offset scores 1 of 20; beams horizontal 2,997 / 3,000, columns vertical 890 / 892), and calibrate() finds it on 7.233
(ANNAPOLIS) and 7.253 (604) too. So the entry covers 7.221, 7.233, 7.243 and 7.253 - every version with evidence; 7.245
keeps its own entry, 7.208 uses 2,944-B slots. Details: `results/sds2_valueerror.md`.

| job | live | v5.4 (repro) | v5.4 + patch | v5.5.3 + patch |
|---|---|---|---|---|
| 6eeedc274302 100_Binney_Slab_Arch_Job | 3, no_member_records_read (v5.4.1) | rc 1 | **164 exact SDS2 B-rep solids, 164 BRep-valid, steel 8.4 t = SDS2 piece weights 8.4 t (1.000); manifest class 1 / A** | identical |
| a47a13079296 100_Binney_Slab_Job | 3, valueerror (v5.5.0) | rc 1 (ValueError) | 1 solid, valid: MISC #3 `Conc. 1.1 yards` written as the concrete_prism stand-in (tagged `[approx: ...]`); manifest class 2 / B | identical |
| 58c969614e6f 100_Binney_Slab_Job | 3, no_member_records_read (v5.5.0) | rc 1 | no crash: "2 members, none with a section or fabricated pieces, 0 placed pieces" -> class 3 / C | identical |
| 5eed44fe33ca Boylston_Job (7.221) | 3, valueerror (v5.5.3) | rc 1 (ValueError) | rc 0: 5,127 member solids from the job's own sections and end points (no fabricated pieces exist in this seed job), BRep-valid 5,127 / 5,127; manifest class 3 / C "members only" | identical |

Open (not claimed either way): in both Slab_Job copies, MISC members 1 and 2 have 74 KB member files that place no piece
per the decoder; whether they hold slab geometry the decoder does not read is an SDS2 decoder question.

Other valueerror rows: the 13 BG PODIUM / Boston Garden rows are v4 results (`PLG12x14x300: built-up dimensions match
neither name nor weight`; `_builtup()` no longer raises since v5.0). Nobody had run v5.x on one: BG PODIUM 332cb8a3 (7.331,
99,662 files, 919 MB) with v5.5.3 on BOX-C: no ValueError: the run got past the profile building where v4 raised and wrote the STEP after 5,774 s: 82,024 exact SDS2 B-rep pieces + 248,107 bolts (142,306 SDS2 bolt pieces), 1 piece not built, steel 17,975 t vs SDS2 piece weights 17,779 t (1.011), 4.9 GB STEP, converter manifest class 2 / B (nominal bolts, mating holes not stored, ...). Converter RSS reached 41.9 GB while writing (observed peak) (above the fleet's 36-45 GB reservation for 0.8-3 GB jobs; one BG copy, bce3a755, already ended as converter_out_of_memory on v5.3): give these 13 re-runs >= 64 GB. Its own read-back (4.9 GB STEP) was still running at 05:05Z; bg.sh uploads rc / log / manifest to agentwork/ifc-verification-residue/sds2_bg/332cb8a3d530bf3aba509ff9/ when it ends. The coordinator already re-opens all class 3 SDS2 rows with v5.5.3.
CSU 15-027 (7.312, 810 COLUMN records with NaN end points) is fixed in the sds2-weights-failures work tree
(`_sparse_try` counts bad points instead of rejecting); that change is not in v5.5.3, so CSU will fail again until it is
merged. Both patches touch `_sparse_try` in separate hunks.

## 2. Far-origin residue of 'members not converted': converter x grader matrix (NEW)

The 14 Baylor Hurd SDS/2 exports (x = -1.456e9, y = 3.036e9 mm) re-run through the fleet worker + coordinator rules with
every converter / grader pair. "Fleet grader" = the fleet's step_check (whole-file translation, skipped when the file has a
MAPPED_ITEM); "second-read grader" = `step_check_far_secondread_vs_fleet.diff` (solid checks from a translated second read,
MAPPED_ITEM files included).

| model | 6.1.2 + fleet grader (fleet today) | 6.1.2 + second-read grader | dev3+vr far mode + fleet grader | dev3+vr far mode + second-read grader | 6.1.2+far_always + fleet grader | 6.1.2+far_always + second-read grader |
|---|---|---|---|---|---|---|
| c951cd2d377d | **1** ; L 0:32 ; 0.2 MB | **1** ; L 0:32 ; 0.2 MB | **2** ; invalid_solids:24 ; L 0:32 ; 0.2 MB | **1** ; L 0:32 ; 0.2 MB | **2** ; invalid_solids:24 ; L 0:32 ; 0.2 MB | **1** ; L 0:32 ; 0.2 MB |
| b79c4f3a9377 | **1** ; L 0:33 ; 0.2 MB | **1** ; L 0:33 ; 0.2 MB | **2** ; invalid_solids:24 ; L 0:33 ; 0.2 MB | **1** ; L 0:33 ; 0.2 MB | **2** ; invalid_solids:24 ; L 0:33 ; 0.2 MB | **1** ; L 0:33 ; 0.2 MB |
| c13135ba64e2 | **1** ; L 0:46 ; 0.7 MB | **1** ; L 0:46 ; 0.7 MB | **2** ; invalid_solids:48 ; L 0:46 ; 0.5 MB | **1** ; L 0:46 ; 0.5 MB | **2** ; invalid_solids:48 ; L 0:46 ; 0.5 MB | **1** ; L 0:46 ; 0.5 MB |
| d9962a0cdfd3 | **1** ; L 0:124 ; 2.2 MB | **1** ; L 0:124 ; 2.2 MB | **2** ; invalid_solids:112 ; L 0:124 ; 1.4 MB | **1** ; L 0:124 ; 1.4 MB | **2** ; invalid_solids:112 ; L 0:124 ; 1.4 MB | **1** ; L 0:124 ; 1.4 MB |
| 708137998946 | **1** ; L 0:123 ; 2.1 MB | **1** ; L 0:123 ; 2.1 MB | **2** ; invalid_solids:107 ; L 0:123 ; 1.4 MB | **1** ; L 0:123 ; 1.4 MB | **2** ; invalid_solids:107 ; L 0:123 ; 1.4 MB | **1** ; L 0:123 ; 1.4 MB |
| 4f6b8e2e9693 | **2** ; parts_without_solid:4, L4-surface:4 ; L 0:129/2:1/4:4 ; 2.5 MB | **2** ; parts_without_solid:4, L4-surface:4 ; L 0:129/2:1/4:4 ; 2.5 MB | **2** ; invalid_solids:119 ; L 0:134 ; 1.7 MB | **1** ; L 0:134 ; 1.7 MB | **2** ; invalid_solids:119 ; L 0:134 ; 1.7 MB | **1** ; L 0:134 ; 1.7 MB |
| e43ef5137745 | **1** ; L 0:107 ; 0.9 MB | **1** ; L 0:107 ; 0.9 MB | **2** ; invalid_solids:74 ; L 0:107 ; 0.6 MB | **1** ; L 0:107 ; 0.6 MB | **2** ; invalid_solids:74 ; L 0:107 ; 0.6 MB | **1** ; L 0:107 ; 0.6 MB |
| 925e43c7b39a | **2** ; open-surface:2 ; L 0:112/1:3 ; 1.0 MB | **2** ; open-surface:2 ; L 0:112/1:3 ; 1.0 MB | **2** ; invalid_solids:83 ; L 0:115 ; 0.6 MB | **1** ; L 0:115 ; 0.6 MB | **2** ; invalid_solids:83 ; L 0:115 ; 0.6 MB | **1** ; L 0:115 ; 0.6 MB |
| 700b4c5c15d6 | **1** ; L 0:143/1:2 ; 1.2 MB | **1** ; L 0:143/1:2 ; 1.2 MB | **2** ; invalid_solids:93 ; L 0:145 ; 0.9 MB | **1** ; L 0:145 ; 0.9 MB | **2** ; invalid_solids:93 ; L 0:145 ; 0.9 MB | **1** ; L 0:145 ; 0.9 MB |
| 944bc6d8f919 | **1** ; L 0:152/1:3 ; 1.6 MB | **1** ; L 0:152/1:3 ; 1.6 MB | **2** ; invalid_solids:139 ; L 0:155 ; 1.1 MB | **1** ; L 0:155 ; 1.1 MB | **2** ; invalid_solids:139 ; L 0:155 ; 1.1 MB | **1** ; L 0:155 ; 1.1 MB |
| 6f3ceef9bdcb | **1** ; L 0:179/1:2 ; 2.1 MB | **1** ; L 0:179/1:2 ; 2.1 MB | **2** ; invalid_solids:189 ; L 0:181 ; 1.3 MB | **1** ; L 0:181 ; 1.3 MB | **2** ; invalid_solids:189 ; L 0:181 ; 1.3 MB | **1** ; L 0:181 ; 1.3 MB |
| 7b35850cd279 | **2** ; parts_without_solid:1, open-surface:14, L4-surface:1 ; L 0:266/1:12/2:2/4:1 ; 2.7 MB | **2** ; parts_without_solid:1, open-surface:14, L4-surface:1 ; L 0:266/1:12/2:2/4:1 ; 2.7 MB | **2** ; invalid_solids:237, open-surface:13 ; L 0:281 ; 1.5 MB | **2** ; open-surface:13 ; L 0:281 ; 1.5 MB | **2** ; invalid_solids:237, open-surface:13 ; L 0:281 ; 1.5 MB | **2** ; open-surface:13 ; L 0:281 ; 1.5 MB |
| cd3313dc0284 | **2** ; open-surface:17 ; L 0:249/1:6 ; 2.1 MB | **2** ; open-surface:17 ; L 0:249/1:6 ; 2.1 MB | **2** ; invalid_solids:172, open-surface:17 ; L 0:255 ; 1.2 MB | **2** ; open-surface:17 ; L 0:255 ; 1.2 MB | **2** ; invalid_solids:172, open-surface:17 ; L 0:255 ; 1.2 MB | **2** ; open-surface:17 ; L 0:255 ; 1.2 MB |
| 7ff7ad6bbfd8 | **1** ; L 0:257/1:3 ; 2.4 MB | **1** ; L 0:257/1:3 ; 2.4 MB | **2** ; invalid_solids:208 ; L 0:260 ; 1.6 MB | **1** ; L 0:260 ; 1.6 MB | **2** ; invalid_solids:208 ; L 0:260 ; 1.6 MB | **1** ; L 0:260 ; 1.6 MB |
| **class 1** | **10 / 14** | **10 / 14** | **0 / 14** | **12 / 14** | **0 / 14** | **12 / 14** |

Reading:
- The fleet today (6.1.2 + fleet grader) loses 2 of 14 against dev3+vr: 4f6b8e2e (4 instances of btp2_M fail in place at
  L0, L0b, L1 and L2 and end as L4 surfaces: 6.1.2's far round skips parts that place shared geometry, `r.frag.needs is
  not None`) and 925e43c7 (two bolts fail in place, their L1 triangulation splits into 3 solids + 2 open surfaces, so the
  far round is never reached). 31 further parts on 7 models are written as L1 triangle meshes of exact geometry.
- dev3+vr's far mode verifies every far part (instances included) on a copy of its own block and its shared block moved by
  one model-level whole-km offset, so all of those stay exact L0. It **must not** run with the fleet grader: the fleet
  rule skips files with MAPPED_ITEM, reads the instances in place, and reports invalid_solids on all 14 (0/14).
- `ifc2step6_6.1.2_far_always.diff` ports that far mode onto 6.1.2 as an opt-in (`V6_FAR_ALWAYS=1`, implies
  V6_FAR_VERIFY). With the second-read grader it reproduces dev3+vr exactly (12/14, same levels / tags / sizes); STEPs are
  30-40 % smaller because far instances stay instances. The two remaining class 2 are source data: SDS/2 grating bars
  and plates given as open shells (13 / 17 open-surface parts), not closable without an owner decision.
- Regression, 15 non-Baylor models (the L2 set below): `V6_FAR_ALWAYS` unset = identical to 6.1.2 on 15/15 (class,
  levels, tags, issues). Set (+ second-read grader) = identical on the 14 near-origin models; the one far model
  (9d37129f, 1 part beyond 10 km) goes from L0 142 / L1 2 / L2 1 to L0 145, class 1 both, 1.3 -> 0.9 MB.
- ALM_Baylor (d713, 113 MB, 15,628 parts):

| ALM_Baylor d713eae4bf9d (113 MB IFC, 15,628 parts) | class | issues | levels | far-origin | STEP | converter s / peak tree RSS |
|---|---|---|---|---|---|---|
| live (6.1.0) | 2 | invalid_solids:383, parts_without_solid:119, open-surface 69 | L0 15394 / L1 103 / L2 12 / L4 119 | - | - | - |
| 6.1.2 + fleet grader (x612_alm) | 2 | invalid_solids:13, parts_without_solid:109, open-surface 69 | L0 15363 / L1 146 / L2 10 / L4 109 | 13 (far round) | 341 MB | 1,368 s / 25 GB |
| 6.1.2+far_always + second-read grader (xfar_alm_sr) | 2 | parts_without_solid:15, open-surface 68 | L0 15612 / L2 1 / L4 15 | 15,628 | 151 MB | 1,156 s / 15 GB |

  The 13 invalid solids of the fleet stack are exactly 6.1.2's far-round rescues: the file contains MAPPED_ITEMs, so the
  fleet grader reads them in place. With the pair: 17,295 solids, all BRep-valid; what is left (68 open-surface + 15 L4)
  is SDS/2 source shells that are open (no owner decision to close them), so the model stays class 2.

Grader memory: the sequential second read (shipped diff) and the concurrent one used for the matrix give identical
output (keys, per-root valid / volume) on 5 far STEPs and 1 near one; peak RSS on ALM_Baylor's 151 MB STEP 2.3 GB vs
4.4 GB, 9.4 vs 11.7 min; small files 0.12-0.16 GB. Near-origin files never take the far path.

Ship as a pair, or not at all: worker env `V6_FAR_ALWAYS=1` + `step_check_far_secondread_vs_fleet.diff`. Then re-run the
far models (the coordinator's re-run list already matches `parts_without_solid` / `v6_L4-surface` / `invalid_solids`).

## 3. Affected models re-run with the current converter (6.1.2 + fleet kit + coordinator rules)

**Per-part verification pending** (sample of 4 of the over-cap models, fleet stack: 6.1.2 + fleet worker with
`step_verify_big` + coordinator rules; labels x612_ppv, x612_ppvb):

| model | before (live) | 6.1.2 STEP | read-back | class / issues |
|---|---|---|---|---|
| f17e943925a2 303011 3D Joists (124 MB IFC) | 6.1: 1,457 MB, text_only, per_part_verification_pending | 1,457 MB (still over the cap) | **streamed** (step_verify_big, 58 chunks, peak 2.1 GB): 160,120 / 160,120 solids BRep-valid, coverage 1.0, 121,402 part volumes checked, 0 outside 5 %; the converter's own per-part read-back agrees (160,120 valid) | **1** |
| 1924e526e9c8 PELOTON OUTPUT PARK (62 MB) | 6.0.x: 1,093 MB, per_part_verification_pending, openings_volume_unverified:553, 1,250 L2 parts | 410 MB (25,637 instances) | ordinary OCC read-back | 2: only 2 open-surface source parts (L0 34,893, no L2 left) |
| e21b8fa4c159 201922 3D joists (37 MB) | earlier snapshot: 932 MB reused, pending (the fleet's 6.1.1 already cleared it) | 404 MB | ordinary | **1** |
| f3852e4be772 RiverPoint Below Level-13 (415 MB) | 6.1: 1,232 MB, text_only, per_part_verification_pending (tags: L2 15, L4 21, open-surface 13) | 1,303 MB (still over the cap) | **streamed** (step_verify_big complete, peak 2.8 GB): 320,885 / 320,885 solids BRep-valid, coverage 0.9999, 4,511 part volumes checked, 0 outside 5 % | 2: parts_without_solid:150 = 148 L4 + 140 open-surface parts whose source shells are open (`open_in_source`; 118 of them `ths*` IfcDiscreteAccessory instances), L2 2; converter + grading 4,599 s, peak tree RSS 9.7 GB |

Sessions 1-2 (dev3+vr, same harness): BOSK_FM 1,389 -> 499 MB, Seaport L4 1,153 -> 585 MB (dev3 itself ran away to 173 GB:
patch E, now in 6.1.1+), Gateway balance-of-plant 1,136 -> 627 MB, Stockton (read-back OOM) 853 -> 207 MB.
Conclusion: no converter-side defect is left in this counter. A re-conversion with the fleet's current converter either
brings the STEP under the 1 GB cap or, when it stays over (joist models with 140k curved parts), the worker's streamed
read-back grades every part; the coordinator has all of them (140 left at 04:1xZ) on its 6.1.2 re-run list.

**Members-not-converted family** (14 Baylor far files with the fleet stack): 10 class 1, see section 2 for the other 4.
**L2 set** (17 models): section 4.

## 4. L2-alt-source parts still produced by the dev3 line (6.1.2 outputs)

L2-alt-source has been an info tag since 00:10Z (lead), so these parts no longer block class 1; this is the record the
item asked for. Sessions 1-2 covered 18 parts / 5 models of dev3 output (`results/l2_evidence.md`). This session took the
live 6.1.x models with L2 parts (17 models, 70 KB - 70 MB), re-ran them with 6.1.2 and ran `tools/l2ev.py` on every L2
part of the new STEP: IFC source item, fallback history, the grader's own read-back, an independent OCC re-read, the exact
kernel B-rep volume of the same IFC product, the largest distance of the STEP vertices to that exact B-rep, and the census.

Result (`results/l2_evidence_612.md`, records `results/l2_evidence_612/*.jsonl`): 38 L2 parts in 10 models. Of the 17
models, 7 have no L2 part any more with 6.1.2 (e5a81c9a, e1828d1c, e0e5a323, c077db42, a949a553, f9aa5a0a, 40dabc98).

- **Same source item: 38 / 38.** Every L2 part is the triangle mesh, by the ifcopenshell kernel, of the product's own Body
  representation (IfcMappedItem -> the map's IfcFacetedBrep; one IfcExtrudedAreaSolid). Its STEP vertices lie within
  0.0036-0.0083 mm of the exact kernel B-rep of the same product (the output grid is 0.01 mm).
- **8 solids (no open shell in the source): valid and volume-exact.** Grader read-back 1/1 BRep-valid each; STEP volume /
  exact B-rep volume 0.99928 ... 1.00051 (6 of 8 within 0.025 %). The census has a volume for one of them (27.9M5, analytic
  7,125,543 mm3: STEP / census = 1.0000); the others are faceted sources without a census volume. Why L0 failed: 5 x the
  transcoder wrote no faces for the mapped IfcFacetedBrep (L0 / L1 no_faces), 3 x the faceted L0 / L1 solid was invalid in
  OCC; the kernel mesh of the same item is valid.
- **3 parts whose source shell is open** (b76a3588 a924_7, e46d3167 M4518 x2): closed at L2 (+2.2 % / +3.5 % against the
  kernel B-rep of the open shell); tagged `open_in_source`, which the coordinator turns into the
  `v6_open_in_source_healed` stand-in (owner rule: never class 1). In e46d3167 the coordinator also flags its 2 L2 parts as
  `v6_L2-alt-source_volume_unverified` because the model has 4 volume outliers; those outliers are other parts (M_2231 /
  M_2232 proxies, 0.948 of their analytic volume), not the L2 parts.
- **27 double-sided rebar meshes** (1fc7a71a rb10745-rb10754 x16, 246fe13f rb10036 x11; every source face is given twice):
  L2 reads back as 32 (26) BRep-valid closed shells per part with a total volume below 0.001 mm3, plus 1 (19) open
  surfaces. They carry `open-surface` (blocking), so these models are class 2 either way. Finding for the IFC improver:
  `judge()` skips the volume comparison when a part also has open shells (`fr.nopen`), so zero-thickness closed shells pass
  as "valid solids". (The improver's 6.1.3-dev adds a related rule - a double-sided source whose single side is open is a
  sheet, no solid tried; I did not test whether it reaches these kernel meshes.)

For the record: every L2 part is the same IFC item; the 8 clean solids are valid and equal the exact geometry (and the
census where it has a volume); the 30 others are open or double-sided source shells and already carry blocking / stand-in
tags.

---

# Part B: sessions 1-2 (dev3 patch and first findings; kept as written at 19:13 local, headings demoted)

Item: 'ifc per-part verification' pending (159 now), 'ifc members not converted' (16), 'valueerror' (15), plus evidence
on L2-alt-source parts still produced by dev3. Method: re-run the affected models with dev3 on BOX-A through the fleet's
own `worker.process` (conversion ladder, step_check read-back, ifc_census, grade_join) and the coordinator's
`classify_ifc` with the live `rules.json` (harness `job/rc.py`, `job/drive.py`). Then root-cause what remained, patch
dev3, and re-run the same models. Nothing was published; all runs wrote only under agentwork/ifc-verification-residue.

Base: `ifc2step6_dev3.py` (md5 f23651e819ec959abb0619fc4a3ae9d0). The fleet kit now runs `ifc2step6 6.1.0-rc`
(= dev4 = dev3 + cleanup), which has the same code at the patched places (kit lines 1702, 2044/2079). The IFC improver's
6.1.1-rc already merged my preliminary upload; see "Changes vs the preliminary upload" below.

### Files (s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/pfix/ifc-verification-residue/)

| file | what |
|---|---|
| `ifc2step6_dev3_verification-residue.diff` | converter patch, unified diff vs dev3 (A, E, F, G, far mode) |
| `ifc2step6_dev3+vr.py` | dev3 with the patch applied (VERSION `ifc2step6 6.1.0-dev3+vr`) |
| `worker_converter_readback.diff` | fleet worker hook (lead decision): per-part join from the converter read-back when the STEP is over the read-back cap |
| `step_check_far.diff` | grader rule (lead decision): far-from-origin files get their BRepCheck / volume checks from a translated second read |
| `sds2_v5.4_verify_step_render_guard.diff` | SDS2 v5.4 `decode/verify_step.py` render guard (KJL ValueError) |
| `results/*.md`, `results/l2_evidence/*.jsonl` | before/after tables, L2 evidence records |

### Converter patch (always on unless noted; each piece independent)

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

### Root causes and results

#### A) members not converted (16, all class 3, all reused old-writer STEPs) -> results/members_not_converted.md
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

#### B) per-part verification pending (159: STEP over the 1 GB cap 155, read-back OOM 4) -> results/per_part_pending.md
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

#### C) valueerror (15, SDS2, not IFC)
- **13 x BG PODIUM_Job** (7.331, z3-sds2-v4): `PLG12x14x300: built-up dimensions match neither name nor weight`.
  Fixed since SDS2 v5 (`_builtup()` never raises); needs only a re-run with v5.3/v5.4.
- **KJL** (7.425, v5.1; 1,812 valid solids were written): the `verify_step.main()` render crashes on an empty triangle
  list (a reference model spread over km). Patch `sds2_v5.4_verify_step_render_guard.diff` draws all items, else skips
  the render (render only). Reviewed, not run (1.1 GB job, SDS2 box).
- **CSU 15-027** (7.312, v5.1): `mem_idx: member work points not found`. v5.4 has the identical `calibrate()` and
  `sparse_layout()`, and the job's mem_idx is 588 MB for about 23.5k members. This is an open SDS2 decoder item; I did
  not patch it blind.

#### D) L2-alt-source parts still written by dev3 -> results/l2_evidence.md (18 parts, 5 models)
- **5 solid L2 parts:** each is the triangle mesh of the same IFC item whose polyhedral L0 failed. All read back valid
  in the grader. Volume is within 0.1 % of the exact kernel B-rep and within 0.04 % of the census analytic volume where
  present. Vertices lie within 0.0087 mm (the output grid) of the exact surface. 4 of the 5 are far-origin cases.
- **13 Camellia DUMMY beams:** surface-only L2. The kernel gives about 386 open shells; the exact B-rep is +13 % against
  Tekla's net quantity. This is source geometry, and these parts already carry the blocking open-surface tag.
- **10 L2-heavy models** (6.0.1: 1-48 L2 parts each): dev3 makes all class 1 with 1 L2 part left; dev3+vr leaves 0 L2.

### Patches to the grader / fleet (lead decisions; not applied by me)
- `step_check_far.diff`: a far file (a CARTESIAN_POINT coordinate >= 1e7 mm) is read twice. Roots, products, faces
  and bbox come from the file; BRepCheck and volume per root come from a copy whose far points are moved by one
  whole-km offset (local frames and the origin stay).
  On dev3 outputs of far models the verdict is unchanged (c951cd2d 40/40, d9962a0c 148/148, 7ff7ad6b 350/350 valid,
  bbox identical). It is required for the far-mode class lift.
- `worker_converter_readback.diff`: when the STEP is over the read-back cap and `<out>.verify_parts.jsonl.gz` exists,
  join with the census from it (`per_part_source: converter_readback`).

### Changes vs the preliminary upload (18:11, merged into 6.1.1-rc by the IFC improver)
- **Removed D** (no instancing beyond 1e7 mm, no ghash dedup for far copies). Far mode makes it unnecessary, and it
  showed no measurable gain. I first attributed the 7ff7ad6b regression to D; it reproduces without D and comes from E
  (see E).
- **Replaced the last-resort far round with far mode.** The last-resort round could not rescue far instances whose
  shared geometry is itself far (SDS/2 world-frame maps).
- **Added G** (near-origin instance dedup false passes, Stockton).
- The grader rule is now the second-read form; the earlier whole-file translation also moved #110 and broke the checks.

### Incident (reported to the coordinator at once)
At 01:14Z I overwrote `_control/z3conv/sds2/pybin.txt` with an empty object (a mistyped `aws s3 cp - <key>` meant to be
a read). The coordinator restored it at 01:17:17Z. Since then every write goes through `job/safe_put.sh`, which refuses
destinations outside my own prefixes.

### Reproduce
`job/rc.py` (worker + classifier with the live rules), `job/drive.py LABEL CONVERTER TARGETS.json`, targets in
`job/targets_*.json`. Diagnostics: `job/diag_far.py`, `job/diag_far2.py` (far origin), `job/probe_kernel.py`,
`job/probe_iter.py`, `job/variant_test.py` (memory runaway), `job/l2ev.py` (L2 evidence). Results live under
s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/<label>/.


### Notes folded in from COORDINATION.md (session 2, agent aa151b3a)
- Patch E geometry effect on the 10 L2 models, per part dev3 vs dev3+vr: 4,565 / 4,592 volumes within 1e-4, 27 differ by
  at most 5.7e-4 (all 27 are kernel parts tagged approx-curved); valid solids 12,394 = 12,394; faces per model -9.7 % to +2.8 %.
- `build_index_converter_readback.proposal.diff`, tested on the real l2_vr4_rb1 records: 9 / 9 over-cap models went from
  class 2 (not_read_back_large_file) to class 1 (graded_by converter_readback); the under-cap one was unchanged. Superseded
  by the lead's 02:05Z rule (streamed read-back first; the converter read-back only as a fallback, never class 1).
