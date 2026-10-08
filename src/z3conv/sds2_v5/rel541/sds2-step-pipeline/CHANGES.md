# sds2-step-pipeline v5.4.1 — changes from the v4 candidate

## v5.4.1 (v5.4 with lower peak memory; same CLI, same outputs)

- `sds2_to_step.py` runs each heavy phase in its own forked child process: the conversion (build + STEP write),
  the `--verify` read-back, and each read-back repair pass (label scan, rebuild, re-verify). One phase's memory is
  returned to the OS before the next starts. v5.4 read the whole STEP back in the converter process while its XCAF
  document, STEP writer model and part caches were still alive, so the peak was the sum of the phases. Windows and
  `SDS2_NO_FORK=1` keep the single-process path.
- `--verify` preview: at most `SDS2_PREVIEW_MAX` (default 6,000) of the largest solids are tessellated. v5.4 meshed
  every solid into Python triangle lists. Counts, validity and bbox still cover every solid. The preview is skipped
  cleanly when nothing is drawable (v5.1 crashed with `zero-size array` on data-3 KJL).
- The temporary assembly check of unique parts is skipped above `SDS2_ASSEMBLY_CHECK_MAX` (default 5,000) parts,
  for example imported reference meshes with 12,000+ parts; the read-back repair pass covers those parts.



## v5.4 (on top of v5.3, same CLI; zip `sds2-step-pipeline-v5.4.zip`)

- **Bolt-derived holes on main members (FIX item 8).** The member-file 658-B blocks that `instances.hole_groups`
  reads are SDS2 bolt records (orientation, head point, bolt diameter, length, π/2, grip), the same records
  `bolts.py` turns into bolts, not hole records. Main members hold no hole records of their own: 7.2/7.3 piece
  files carry 0-diameter markers only, so SDS2's NC holes on beams and columns appear nowhere as holes.
  - v5.4 takes every decoded bolt: an SDS2 bolt record, or a nominal bolt through a stack of ≥ 2 coaxial decoded
    holes.
  - For each exact piece whose own material the bolt line crosses between head and head + grip, it cuts a hole
    over that material span only, unless the piece already has a coaxial decoded hole there.
  - The diameter is copied from a coaxial decoded round hole of the same bolt. With none, nothing is cut and the
    case is listed (`holes.holes_not_cut.by_reason`).
  - Bolts that stop at a single decoded ply are never extended into a web.
  - Parts with derived holes are named `... (piece N) [derived: bolt record + coaxial hole: k hole(s)]`. The
    manifest has `holes.derived` (count per piece, bolts checked).
  - SDS2 bolt / nut / washer pieces, turned pieces and concrete are excluded.
  - A derived hole that would split a part (cylinder along an edge or through a thin tip) is not cut; reason
    `derived hole would split the part`. The read-back repair pass covers derived-hole parts that read back
    invalid (AGNEWS-T: 5,786 / 5,786 valid).
  - Decoded single-ply holes whose mating piece has no hole in the data are counted in `holes_not_cut` and as
    stand-in type `mating_holes_not_stored`. This is the owner's "pieces without holes" case, so the job is class 2.
- `qa/nc1_holes.py --manifest --pieces-csv`: NC1 per-part matched / missing / extra counts including derived holes,
  only real holes (BO lines with a diameter; 0-diameter lines are marks) and only pieces placed in the model.
- Greenwood NC1 (12 placed matched parts, 90 holes): 0 matched in v5.3 and v5.4. Its beam holes are single-ply
  connections with no SDS2 bolt record, which the rule does not extend. Derived holes therefore stay a class-2
  stand-in (`holes_derived_from_bolts`).



## v5.3 (on top of v5.2, same CLI; zip `sds2-step-pipeline-v5.3.zip`)

- **Converter duplicates (FIX item 12):** the key is now (piece, origin on a 0.1 in grid, rotation to 1e-2). The two
  members of a connection can store the same piece 0.005-0.01 in apart, and the 0.01 in grid split those (AGNEWS-R
  7.331 bolt pieces at z -14.87 / -14.88). Data-4 box set: 215 converter duplicates in v4, 42 left in v5. AGNEWS-R:
  16 → 2.
- `qa/nc1_holes.py`: cross-check of decoded holes per piece against NC1 / DSTV files (see Known limits).



## v5.2 (on top of v5.1, same CLI; new zip name `sds2-step-pipeline-v5.2.zip`)

- **Reference models with open surfaces:** imported DWF meshes whose faces don't close were left out in v5.1 (data-3
  n2: 99,656 of 101,751 parts). v5.2 writes them as SDS2's stored faces, sewn into shells, tagged
  `; open surface, not a closed solid`. Manifest `counts.reference_open_shells`; the job is graded class 2 corpus R.
  `verify_step` counts free shells as leaves. Example: DFGH 7.425 gives 940 parts (149 open), all valid on read-back.
- **Unlinked reference variant (data-3 duct-l5 / pp3):** the 538-B blocks carry the matrix, origin, a per-object GUID
  and an RGBA colour, but piece id 0. There are 68,869 blocks, 68,869 unique GUIDs and 14,446 piece files, and the
  GUIDs appear in no piece file and not in `subm_idx`. The piece link is absent from the stored data, so nothing can
  be placed without guessing. Manifest: class 3, corpus R, with the frame count as proof
  (`counts.reference_unlinked_frames`). v5.1 graded these broken.
- **Seed / empty jobs with members but no geometry** (DWS_SEED_JOB_STRUMIS: one MISC member, no section, no pieces):
  class 3, corpus C, with proof (member counts, 0 placed pieces). v5.1 graded these broken.
- **Joist depth:** comes from the designation when the 7.6 boost record carries d = 0 or a depth that disagrees by
  more than 25 % (BACK UP MILL_OFFICE 7.613 18LH09). v4 wrote no solid for these joists at all.



## v5.1 (on top of v5, same CLI; zip `sds2-step-pipeline-v5.zip` replaced)

- **Imported reference models (data-3: most "no members" / "STEP write failed" 7.3xx-7.6xx jobs from training
  archives):** one member of type `DWF Import` / `ReferenceModel` places thousands of piece files that have no
  piece-table entry (hyf 7.425: 17,923 placements of 12,902 pieces; v4 wrote 0 solids). v5.1 writes each placed
  piece from SDS2's own stored B-rep (no approximation; a part whose faces don't close is left out with reason
  `reference_part_no_closed_brep`), named `... / reference part (piece N, inst K) [reference: imported model geometry
  as stored by SDS2, not fabricated steel]`. Manifest: `counts.reference_parts`; a reference-only job gets
  **corpus R**, class 1 or 2 by fidelity.
- **Empty jobs** (no member files; zero-filled 300 MB indexes in training sandboxes): manifest with
  `empty_job_proof` (member files 0, mem_idx size, non-zero bytes, piece files), class 3; same failure reason as before.
- **Read-back repair:** solids that are valid in memory but invalid once the STEP is read back (AGNEWS-T,
  METHODIST, FERNDALE) are found by name after `--verify` (`verify_step.invalid_labels`), rewritten as placed copies
  (pass 2), and left out with reason `exact_solid_invalid_at_placement` if still invalid (pass 3).
- **Grating:** `GR...` pieces are treated like `GT...` (solid panel tagged, kept out of the steel tally; GM M5 FLINT
  1.30x -> within range).
- **Dominant weight outliers:** a single piece whose SDS2 weight disagrees with its geometry by more than 25 % of the job's
  total (DOWCORNING 7.039: `BPL240x240` recorded at 447,816 of 549,800 lb) is listed under
  `weight_check.dominant_outliers` and the class uses `ratio_without_outliers` (DOWCORNING 0.224 -> 1.016).
- **7.7+/8.0 joist pieces whose multi-body B-rep does not close** (TYSONS 7.720: 20, previously skipped or boxed):
  open-web joist derived from the designation over the piece's own length, tagged `derived_from_designation`.
- **No guessed part is silent, none is class 1:** class-1 tolerance removed. Designation-derived joists, built-up
  sections sized from weight (tag now also on member envelopes), concrete prisms, straight-rod stand-ins for
  hooked anchors (`special_solid`), nominal bolts, slab stand-ins all carry `[approx: ...]`; every manifest group has
  a `needed` field (what the source lacks: real section dimensions, vendor joist design, ...).
- `mem_idx` slot-size ambiguity resolved by validation + version family (7.323 Tarrier); KNOWN member types include
  the import types.

# v5 — changes from the v4 candidate

Base: `sds2-step-pipeline-v4-candidate.zip` (sha256 c5b65d27…, the build used for data-4 and Disk-2 run 2; newer than
`sds2-step-pipeline.zip`, which lacks the built-up-profile, round-HSS-wall, 8-orientation and `inst` changes). The
run-2 "v5-candidate" zero-area guard is included. Entry point and CLI are unchanged:

```
python decode/sds2_to_step.py <job> -o <name>_stage2.step --stage 2 --verify
```

Outputs are the v4 set plus one new file, `<name>_stage2_manifest.json` (the per-job sidecar described below).
`_pieces.csv` has two new columns: `standin` and `also_on_member`. Log lines parsed by `batch/run_batch.parse_log`
(`solids: {...}`, `ratio`, `N top-level shapes`, `BRep valid: N`, `model bbox`) are unchanged.

## Fixes, in the requested priority order

| # | FIX item | what v4 did | v5 |
|---|---|---|---|
| 1 | 10 angle legs swapped | The exact SDS2 B-rep path (which builds 95-100 % of pieces on 7.1-8.0 jobs) was never affected. The approximate profile builder already tried 8 orientations, but it scored them on boundary hits first, and it fitted against every vertex record, including unreferenced ones. | The approximate builders fit only the vertices that the piece's own faces reference (`instances.piece_vertices`). An orientation whose y/z extents match the vertex box within 0.05 in now wins outright (score = bbox-ok, then hits, then bbox error). |
| 2 | built-up PLG / WPS / WBX | Read +0x5A/+0x62/+0x6A/+0x72 (stage 1 PLG 1.000, WPS 1.005 on Binney), but `profile()` raised `ValueError` whenever a record lacked those fields or failed the 2 % check. That aborted the whole job. | `_builtup()` never raises. The order is: (1) record fields that reproduce the weight within 2 %, or that match the PLG name; (2) dimensions from the PLG name; (3) flanges sized from the recorded weight; (4) bounding rectangle. Options (3) and (4) are tagged `[approx: …]`. |
| 3 | 3 / 2 HSS-pipe hollow, round 1.19× | The exact path was hollow (median 42 faces). The approximate path already kept inner loops, and the round wall was already nominal-vs-design corrected. | Kept as in v4. Verified: HSS hollow share 100 %, ROUND stage-1 median 0.996, ROUND stage-2 0.996. |
| 4 | 11 / 13 HSS orientation / extent, stray vertices | Piece files carry vertex records that no face uses (HSS reference squares: an HSS12x2 file has points 12 in apart across its 2 in side; also work points and hole markers). The approximate builders, and the verifier's G5 rebuild, used them, so a 10×6 tube looked 10×10. | The approximate builders use only face-referenced vertices. `qa/v5check.py` reports G5 both ways: against the face vertices (the true geometry) and against the raw records with the EC-45 rule (the verifier's method). The raw-record "mismatches" on exact pieces are a verifier artefact, not a STEP defect. |
| 5 | 6 skipped placed pieces | The orthonormality test `abs(M Mᵀ − I).max() > 1e-3` lets NaN through, because NaN > tol is False. Coincidental piece-id hits next to overflowing doubles became "placements". Binney: 737 phantom blocks; 597 were reported as skipped and **140 were written with NaN placements**, giving 700 STEP syntax errors and 140 unresolved references on read-back. Greenwood: 29 phantoms and 1 NaN component. | `instances._is_frame()` (NaN-safe, \|det\| = 1) applies in all layouts, and `placement()` refuses non-frames. Pieces that really have no usable builder, or whose approximation exceeds 5× SDS2's weight (CHOWNS: 34 bent plates whose convex hull fills the bend), get an L×W×T / nominal-section stand-in, tagged, instead of being dropped. |
| 6 | 12 same piece for two members | Written once per member listing it. | Key = (piece, origin to 0.01 in, rotation to 1e-3). A repeat from a different member that is not an SDS2 twin (same type, section and end points) is skipped. The writer's row records `also_on_member`, and the manifest lists every skipped duplicate. |
| 7 | 4 repeated names | `(piece N, inst K)` was already in v4c; bolts carry `(inst K)`. | Unchanged. S3 duplicate names = 0 on every regression job. |
| 8 | 13 stray vertex records | see 4 | see 4 |
| 9 | 5 bent plates 0.41× | The exact path builds bent plates; the 0.41× figure came from the approximate builder. | The approximate bent-plate path uses face vertices. Over-5× hulls become tagged slabs. |
| 10 | 1 joists as solid blocks | d × 6 in boxes, 100-260× SDS2's weight per foot (Greenwood: 205 of 205). | `decode/joist.py` derives an open-web joist from the designation, in stage 1 and stage 2. The depth comes from the designation and record. Chords are back-to-back angle pairs and the web is round-bar diagonals at ~45° panels. Mass is the SJI typical weight for K series and a depth/size estimate for LH/DLH. SDS2's 2.5 / 5.0 lb/ft are series placeholders, so they are not used. Tag: `derived_from_designation`. Greenwood M2 solid-block share: 100 % → 0 %. |
| 11 | 8 holes / copes | The exact path cut holes and slots (Binney 110,784). Approximate pieces had no holes. | Approximate pieces now get their decoded holes cut too. Their copes are not modelled, and the tag says so. |

## Other fixes found during regression (they made jobs fail or be rejected)

- **Invalid solids at a placement:** about 1 exact part in 10,000 is valid locally but invalid at one of its assembly
  placements. The kit rejects such jobs (`valid != solids`; data-4 had 13 jobs with 1-22 of them, for example
  AGNEWS-T `COLUMN #427 / HSS8x4x5/16`). v5 BRep-checks every placed instance. A failing instance is written as a
  placed copy, with ShapeFix if needed. If no form is valid, the instance is dropped and reported as skipped
  (`exact_solid_invalid_at_placement`).
- **NaN member end points:** these made OCC dump core in the stage-1 prism (data-4 ANUSHA_JOB, AMOL_Job 7.135:
  "other", rc 139). `to_step.frame()` now rejects non-finite or absurd end points and rolls.
- **ZeroDivisionError in `plate_outline`:** a zero or non-finite target area from the piece weight (data-3 7.425 /
  7.433, 2 jobs). It is now guarded.
- **Stage 1 with no structural members:** v4 raised `IndexError` on `rows[0]`. v5 writes the members CSV with a
  header only.
- **Ambiguous `mem_idx` slot size:** when several slot sizes divide the file (7.323 Tarrier: 1280 and 2944),
  `sparse_layout` returned None ("too few members to calibrate"). v5 validates every candidate. It counts only
  known member types and breaks ties on the job version's slot family.
- **Exact B-rep without an SDS2 weight:** v4 refused the exact geometry whenever the piece weight was 0. v5 accepts it
  when the B-rep extents equal the piece table L×W×T, or the table length for rolled pieces.
- **Corrupt numbers:** solids larger than about 3 miles (corrupt source numbers) are reported, not written. Pieces with
  absurd solid weight (over 1e7 lb) or weight under 0.001 lb are kept out of the steel tally (run-2 GHTUG canary:
  ratio 2.8e214).
- **Empty jobs:** jobs with no member files get a manifest (class 3, "empty job") and fail with the same message as
  before, so batch reasons are unchanged.
- **`verify_step`:** reports STEP load errors (syntax / unresolved references) and returns its results, which are
  merged into the manifest.

## Stand-in tagging

Every solid that is not SDS2's exact piece geometry has a STEP product name ending in `[approx: <what and why>]`.
For example:

- `JOIST #57 / 24K6 (joist stand-in) [approx: derived_from_designation open-web joist 2L2.00x2.00x0.138 chords + …]`
- `BOLT 0.75 x 1.25 grip (nominal heavy hex) (inst 12) [approx: bolt guessed through a decoded hole stack …]`
- `BEAM #12 / W12x26 (piece 345, inst 1) [approx: section profile extruded …; copes/cuts not modelled; holes cut (…)]`

Exact pieces keep the v4 name format unchanged. The verifier's `(piece N, inst K)` parsing still works, and a
trailing tag only follows the closing parenthesis.

## Sidecar `<name>_stage2_manifest.json`

- `counts`: members, members with pieces, members without geometry, placed pieces (decoded), pieces written
  (exact / approx), envelopes, joist stand-ins, SDS2 / nominal bolts, solids written, skipped, converter duplicates.
- `standins`: totals `by_type`, plus `groups` (type, real type, reason, count, every STEP label).
  - Types: `joist_openweb_standin`, `joist_envelope_box`, `member_envelope`, `nominal_bolt`,
    `rolled_profile_extrusion`, `plate_from_vertices`, `piece_table_standin`, `grating_solid_panel`,
    `holes_not_cut`, `concrete_prism`.
- `skipped`: every placed piece not written, with its reason.
- `converter_duplicates`: every skipped duplicate, with the member it was written with.
- `weight_check`: STEP steel vs SDS2 piece weights in total and `by_family`, plus the joist stand-in tonnage.
- `readback`: OCC read-back results (solids, valid, invalid, load errors, bbox).
- `class`, `corpus`, `class_reasons`. `manifest.classify()` documents the rules:
  - **1 / A:** no stand-ins, nothing skipped, steel within 0.9-1.1 of SDS2.
  - **2 / B:** tagged stand-ins or skipped pieces.
  - **3 / C:** members only, or an empty job.
  - **0 / broken:** write failed, invalid or unreadable solids, steel outside 0.75-1.3, or more than 5 % skipped.
- Concrete prisms do not by themselves keep a job out of class 1. `SDS2_CLASS1_TOLERATE=joist_openweb_standin,...`
  (environment) adds more tolerated types, for example to count designation-derived joists as complete.

## Regression tool

`qa/v5check.py <job> <step> [--stage 1|2] [--placed-validity] -o metrics.json` reads the STEP back with XCAF. It
reports M1 by family, M2 joists (solid-block = more than 50 % of the d × bf envelope), S3, G4
(converter-introduced vs twins), G5 (faces and EC-45 records), the HSS face counts and the stand-in tags.

## Known limits

- Copes, cuts and bevels exist only where SDS2's piece B-rep is used, which covers 95-100 % of pieces on 7.1-8.0
  jobs. 6.3xx jobs (for example CHOWNS, defaultAdapt) have no readable face topology, so all their pieces are
  approximate (tagged).
- Joists in 7.0-7.6 jobs are derived from the designation. Their chord and web sizes are typical, not the vendor
  design. 7.7+/8.0 jobs store joists as pieces, and those are exact.
- Nominal bolts: diameter and grip come from the hole stack. Length, head side and washers are not in the data.
- **Main-member bolt holes are not cut.** On 7.2 / 7.3 jobs the holes of the main material (beams, columns) are not
  in its piece file: they are in member-file hole blocks. Greenwood NC1: 26 matched parts, NC1 lists 392 holes, the
  piece files hold 4. The holes in connection-material piece files are cut (Greenwood 347, Binney 110,391).
  Member-block decoding exists for 7.243 (`instances.hole_groups`) but is not yet cut into the solids. The 7.312
  block layout is not decoded.
- Welds are not modelled (no readable weld geometry).
- Stage 1 (`--stage 1`) members still run on the work line (FIX item 9: this is by design, an erection-level model).
