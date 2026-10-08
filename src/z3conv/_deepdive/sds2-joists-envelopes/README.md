# SDS2 class-2 reasons `joist_as_envelope_box` and `member_as_envelope`: deep dive

Owner agent for the fix: **sds2_fixer**. All patches are drop-in, against the running converter
`z3conv/sds2/sds2-step-pipeline-v4-candidate.zip` (sha256 c5b65d27..., label v4) and the two kit workers. Nothing outside
this folder was modified.

## TL;DR

- On 2026-10-01, 9 SDS2 models were class 2. Four of them carry these two reasons:
  0020b0 BAHAMAR 7.135 (reused, disk-2 run 2), 076459 WLCSC 7.331, 1f207d bghjk 7.331 and 86b590 hk 7.331.
  The status counter's "70 / 8" counts stand-in rows (one per designation), not models. In the data-4 run with
  the same converter, **58 of 150 converted jobs (39 %) had joist envelopes (22,596 joists)** and 99 had non-joist
  envelopes (6,447 members). Expect the same order of magnitude in the 3,700 SDS2 jobs still pending in data-3.
- The reasons have **five different root causes**. Three are converter bugs, one is a mislabel in the worker and
  grader, and one is a genuine source limit:

| # | finding | kind | cases | fix |
|---|---|---|---|---|
| 1 | Pre-7.7 joists are written as **solid d x 6 in boxes**: 18K3 at 28 ft = 10,248 lb instead of ~185 lb. WLCSC: 1,512 t of phantom steel against 96.7 t of real steel | converter representation gap. The job **genuinely has no chord/web data** | all 7.0-7.6 jobs with joists | `joist_catalog.py`: an open-web joist built from the designation, using SDS2's own BIMJoist/Vulcraft catalog (shipped in the corpus job folders) plus measured seat depths. Tagged as a stand-in |
| 2 | **Member type read from the wrong mem_idx slot** in the f32 families (1280-B 6.3/7.0 and 1416-B 7.1 slots): type of member n is stored at slot n+1 | converter bug | BAHAMAR 406 of 4,471 members mistyped. Its 76 `member_as_envelope` rows are all joists (`BEAM 24K8`, `COLUMN 20K10`, ...). Also CHOWNS 6.336, ANUSHA/AMOL 7.135, defaultAdapt 6.322 | `sds2job._type_shift` (contradictions 194 -> 0 on BAHAMAR) |
| 3 | `joist_as_envelope_box` is assigned whenever the **member type** is JOIST, even when the section is a rolled W/HSS/L. A Revit-imported job types all framing JOIST | worker + grader labelling bug (the geometry is already the exact W profile) | bghjk: 1,303 "joists" W14x22, W24x55, ... | label by section (`member_standin()` in kit `sds2/worker.py` and `grade/worker.py`, plus the builder name in `to_step2`) |
| 4 | Members with **no material in the job** (Revit-imported or never-detailed members: placement-only 116/136-B member files; 7.7 member files holding only a connection-component archive) | **genuine source limit**. The stage-1 solid is already the exact nominal profile on the work line | hk 3,090 (Revit), bghjk 1,303, data-4 TRAINING_5 646, 121_Seaport 757, LINE 62 DOCKS 7.708 208 | new tag `member_undetailed_profile` -> stand-in type `member_undetailed_nominal_profile`, kept separate from real decode misses (`member_envelope`) |
| 5 | **Joists with attachment pieces but no joist piece are dropped entirely** (no envelope, no skip row), so the grader cannot see the omission | converter bug | NY Bridge 7.425: 24 of 67 joists (only their PL3/8 bearing plates were written). MORROW 7.720: 16 + 23 | `to_step2`: write the joist body when no joist-designation piece is present |

- After the fix, models whose only stand-ins are joists or undetailed members are **still class 2** under the current
  rule ("no stand-ins"). They are now honestly typed as *source-limited*. Owner decision: `coord/build_index.py`
  already has `RULES['tolerated_standin_types']` (and a comment saying "owner decision pending"). Adding
  `joist_openweb_from_designation` and `member_undetailed_nominal_profile` there would move these models to class 1.
  This is defensible because the source holds nothing more. It is a policy call, not a converter fact.

## 1. What the SDS2 job actually stores for a joist (pre-7.7)

Checked on WLCSC 7.331, BAHAMAR 7.135, NY Bridge 7.425, Franklin Park 7.516 and Greenwood 7.312. The scripts are in
`evidence/`.

- **job_mtrl joist record** (table string "SDS2 Pre 7.0 USA", type byte 7). 7.2/7.3 use fixed 510-B big-endian records.
  7.4-7.6 use the little-endian archive with the same fields. Dumped records: `12K1`, `18K3`, `14KSP`, `76DLH-SP1` (WLCSC);
  `10K1`, `16K2`, `16K3`, `16K4` (NY Bridge); `28LH09` (Franklin Park):
  `d` = nominal depth; `bf = tf = tw = 6.0` (placeholders); `k = 0.375`; then the field that `sds2job` decodes as
  **`weight` is the seat depth** (2.5 for K, 5.0 for LH/DLH). Proof: it equals the measured height of the joist end above
  the supporting beam on 596 + 28 + 29 + 364 joist ends, and equals the catalog `bearing_depth`. sds2_v5 `joist.py`
  calls it a "placeholder weight". The record continues with d again, bearing gage (3.25 K / 4.0 LH-DLH), 6.0, 4.275,
  4 x gage, one depth-only number, and the seat again.
  **Records of one depth are byte-identical across size numbers** (16K2 = 16K3 = 16K4; 18K3 = 18K10): no chord, web or
  weight data exists for the designation.
- **mem/<n>** of a joist = 116 B (7.1) / 136 B (7.3): the placement only. No material blocks. The subm table has no
  joist pieces.
- **mem_idx slot**: work points, roll, section, the plan and sloped lengths (+0x80A / +0x812), and per-end blocks with
  small values (0.5 / 0.75 / 1.0). Nothing describes the chords or web.
- **Work-point datum** (`evidence/joist_datum.py`). On 7.0-7.6 the joist end sits exactly one seat depth above the
  supporting W beam's work line (= TOS): WLCSC 28/28 at +2.5; Greenwood 230 at +2.5, 58 at +5.0, 36 at +7.5;
  NY Bridge 28 at +2.5. So the work line is the top of the top chord. On 7.7+ it is the seat bottom: MORROW 7.720
  has 1,560 of 1,596 ends at +0.0.

**Verdict:** for 7.0-7.6 joists the source genuinely lacks joist detail. The best achievable geometry is derived:
designation, catalog, measured seats. It must be tagged as a stand-in.

### What SDS2 itself draws when it does model a joist (7.7+ ground truth)

MORROW HS 7.720 stores joists as pieces. `evidence/joist_groundtruth.py` decoded all 129 unique joist pieces
(`evidence/MORROW_7720_joist_groundtruth.json`):
- Chords: back-to-back angles, **t = 1/4 in on every piece** (0.253-0.256 from volume / length). **Top-chord leg =
  BIMJoist catalog leg on 60 of 63**, bottom chord on 71 of 105 (the misses are catalog 1.25 vs SDS2 1.5 on
  16K3/18K3/18K4/20K4/22K4, a newer table).
- Seats: 4 small angles, 2.5 in deep for K, 4 in long.
- **Web: a solid plate filling the gap between the angles** (127 of 129 pieces; 1.0 / 0.56 / 0.125 in thick). SDS2's
  joist weight is therefore ~9x the real joist: 24K4 at 32.7 ft = 2,513 lb = 76.8 lb/ft (SJI 8.4). The exact solid
  matches SDS2's weight at 1.002x. So the existing "exact" 7.7/8.0 joists are faithful to the source but schematic.
  The README claim "30K10 within 0.2 % of SDS2" compares one schematic against another. This is noted, not changed.

## 2. The derived joist (`patch/decode/joist_catalog.py`, `joist_catalog.json`)

Sources, most specific first. Every value records its source in the STEP name.
1. **Job**: depth (record d, else the designation), work points, slope, roll. **Seat depth per end measured from the
   supporting beam** (`support_seats`: beam work line within 6 in of the end in plan, 2-8 in below). Measured values
   that differ from the record: WLCSC 76DLH-SP1 7.44 in (record 5.0); Greenwood 36 LH ends at 7.5; BAHAMAR 75 K ends
   at 3.5 and 21 at 5.0. Otherwise the record seat depth; otherwise the catalog.
2. **Catalog**: SDS2's BIMJoist material file `plugins/BIMJoist/joists.xml` ("Vulcraft 2003", 346 designations,
   byte-identical in every job that ships it, sha256 5641232a...e830). From it: chord angles, filler gap, seat angle,
   bearing length and bottom-chord setback. Converted by `patch/tools/build_joist_catalog.py`. Designations without
   chords (44/48LH, DLH, SLH, specials such as 14KSP, 18K-SP, 76DLH-SP1) use the nearest catalog size, or legs sized
   from the weight.
3. **SJI typical weight**: the K table is the same as sds2_v5; LH/DLH were transcribed (+-1 lb/ft). This only sizes
   the web bars (`CHORD_T = "catalog"` keeps SDS2's own 1/4 in chords; `"sji"` thins them to hit the SJI mass).
4. **Panel layout**: SDS2's JoistMtrl macro (in the corpus macro folders), rise = depth - 1, diagonals at about
   45 deg, first diagonal 6 in from the end. Round-bar web, 1/2-1 in (K) or 3/4-1 1/2 in (LH/DLH).
5. **Datum**: top of top chord on the work line for 7.0-7.6, seat bottom on the work line for 7.7+.

Builder `joist_openweb_catalog`; STEP name e.g.
`JOIST #183 / 18K3 (joist stand-in) [approx: open-web joist 18K3 derived from the designation - chords 2L1.5x1.5x0.250 top / 2L1.25x1.25x0.250 bottom (catalog 18K3 (BIMJoist/Vulcraft 2003)), 1 in round-bar web (...), seat 2.5 in (...), 8.86 lb/ft vs 6.6 (SJI typical weight); the SDS2 job stores no chord/web data]`.
Identical joists (designation, depth, seats, length to 1/16 in, datum) share one assembly part.
Smoke test: 356 designations x 3 lengths x 3 seat/datum variants = **80,676 solids built, 0 BRep-invalid**.

## 3. Patches

| file | applies to | content |
|---|---|---|
| `patches/01_v4_pipeline.diff` | v4 zip contents (`patch -p1` inside the extracted zip; dry-run verified on a fresh extraction) | `sds2job.py` type-slot fix; `to_step2.py` joist body (incl. attachment-only joists), honest envelope tags; `to_step.py` stage-1 joists; `run_batch.py` `joist_openweb` count + qa reason |
| `patch/decode/joist_catalog.py`, `patch/decode/joist_catalog.json` | new files -> `sds2-step-pipeline/decode/` | derived open-web joist + catalog |
| `patches/02_kit_sds2_worker.diff`, `patches/03_grade_worker.diff` | `z3conv/sds2/worker.py`, `z3conv/grade/worker.py` (made against the 2026-10-01 15:40 versions; these files are being edited, so `patches/apply_standin_remap.py` applies the same change by anchored replacement) | `member_standin()`: stand-in type by section and builder |

Stand-in types after the fix (kind `member` rows):

| builder | stand-in type | meaning |
|---|---|---|
| `joist_openweb_catalog` (also v5 `joist_openweb_standin`) | `joist_openweb_from_designation` | source-limited: joist derived from the designation |
| `joist_envelope_approx` with a joist designation, or any member row whose section is a joist designation | `joist_as_envelope_box` | the old box (only if the derivation failed; also re-labels old CSVs) |
| `member_undetailed_profile`, or `joist_envelope_approx` on a rolled section | `member_undetailed_nominal_profile` | source-limited: no material in the job, exact nominal profile on the work line |
| `member_envelope` | `member_as_envelope` | member has a material reference that was not decoded (possible converter gap) |

The grade-worker remap also fixes **reused** results without re-conversion: BAHAMAR's 76 `member_as_envelope` rows
become joists, and bghjk's 1,303 "joist" rows become `member_undetailed_nominal_profile`
(`evidence/standin_remap.py` output below).

To build a new converter: extract the v4 zip, `patch -p1 < 01_v4_pipeline.diff`, copy the two `joist_catalog.*` files
into `decode/`, re-zip, then update `converter.json` (sha256, label e.g. `v4j`) and set `redo_labels` for jobs whose
results contain joist/envelope stand-ins. Then apply 02/03. sds2_v5 (`v5work`) has the same `read_members` tail
(type-slot bug present) and its own `joist.py`, with invented chord legs `b = 1.25 + d/32` and the seat field read as
weight. Replace its `J.joist_solid` call with `JC.joist_part` + `placement` exactly as in the v4 diff.

## 4. Before / after on real jobs (local runs, v4 vs v4 + patch)

| job (version) | before | after |
|---|---|---|
| WLCSC 076459 (7.331) | 46 joists as boxes: 12K1, 18K3, 14KSP, 76DLH-SP1 = 1,512 t phantom steel. 18K3 #183 10,248 lb | 46 open-web joists, 35 t; 18K3 #183 247 lb, 26 solids. 1,213/1,213 solids valid after read-back, bbox unchanged, steel ratio 1.012 unchanged. Seats measured: 28 ends at 2.5, 16 DLH ends at 7.44 |
| BAHAMAR 0020b0 (7.135) | types shifted: 700 JOIST boxes + 76 "BEAM/COLUMN/MISC without piece data" (all joists) + 76 beams labelled JOIST | see `runs/after/BAHAMAR*.log` (filled below) |
| NY Bridge 64a2e2 (7.425, data-4) | 43 joist boxes; **24 joists missing** (only bearing plates); 10 rolled members as `member_envelope` | 67 open-web joists (24 with their plates); 10 `member_undetailed_profile` |
| bghjk 1f207d (7.331, Revit import) | 1,303 `joist_envelope_approx` -> `joist_as_envelope_box` "joist W14x22" ... | identical geometry (1,303 solids, 1,159.2 t, same bbox); builder `member_undetailed_profile` -> `member_undetailed_nominal_profile` |
| hk 86b590 (7.331, Revit import) | 3,090 `member_as_envelope` + 69 joist boxes | (not re-run locally: 1.1 GB) undetailed members are the same source state as bghjk (139 subm files for 3,234 members); joists 20K5/24LH06/24LH08/28LH08 become open-web |

Images: `evidence/WLCSC_before_18K3_elev.png` vs `evidence/WLCSC_after_18K3_elev.png`, and
`evidence/WLCSC_before_76DLH_elev.png` vs `evidence/WLCSC_after_76DLH_elev.png`. These are elevations projected from
the STEP read-back, with the joist in orange and the supporting steel in blue.

## 5. Not handled / follow-ups

- Joist girders (G/BG/VG, e.g. 48G8N8.8K) are not parsed and stay boxes. No case was found in the samples.
- Top-chord extensions and bottom-chord extensions are per-joist SDS2 options. They were not located in the 7.3
  member slot (MORROW 7.7 shows TCX 25 in on some joists). The derived joist runs work point to work point.
- 7.7+/8.0 "exact" joists carry SDS2's solid web plate (~9x real mass). That is faithful to the source. Only the
  owner can decide whether to render it as open web.
- The LH/DLH SJI weights were transcribed from the SJI tables and should be spot-checked. They only drive the web
  bar diameter.
