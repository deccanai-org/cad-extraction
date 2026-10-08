# sds2-step-pipeline v5.5.11-rc2 — changes from the v4 candidate

## v5.5.11-rc2 (v5.5.10-rc + duplicate placements kept apart + hole-cut guard; same CLI) — canary

rc2 replaces rc (364281d5). rc took "same vertex centroid and box" as "same solid", so it dropped one rod of crossing
X braces (data-3 ca1a958a MISC #174 / #175 RB3/4). rc2 compares the placed vertex sets point by point (0.02 in).

From the sds2_step_verifier review (its G4 check found identical solids our grading did not count).
- **(a) Converter-made repeats are written once.**
  - Case 1: one SDS2 piece id under two members as the identical solid. The old key needed the same frame; the frames
    can differ by a symmetry of the piece. Examples: data-3 8d3cfac8 7.132, PL3x26 piece 1 under COLUMN #9 / BEAM #65,
    61 / 64 and 62 / 63; AGNEWS-R PL3/8x4 piece 88 under members 95 / 97.
  - Case 2: a member's main material read from its header block and again from a material block (the verifier's
    EC-27). Example: ca1a958a member 24 FB1/4x6 piece 705.
  - "Identical" means every placed vertex of one copy has a partner in the other within 0.02 in, both ways. Two
    members can store one plate 0.002 in apart. Box + centroid is not enough (X-brace rods share both).
  - Each repeat is listed in `converter_duplicates_removed`, and in the existing `converter_duplicates` /
    `converter_duplicates_skipped`. The kept row names the other member in `also_on_member`, so the verifier's C1
    counts it as present.
- **(b) Source duplicates are kept as stored and listed** in `source_duplicate_placements`, as info only, with an info
  line in class_reasons. They never change the class.
  - Covers: the same piece twice at one transform in one member (6eeedc27 piece 4134, 2: stays 1 A), twin members
    (1f9bb631 railings #7 / #9, 4: stays 1 A), and two piece records with one solid.
  - Twin members = same type, section and work line, whichever end is stored first.
- `counts.duplicate_placements` = (a) + (b); `counts.source_duplicate_placements` = (b).
- **Side effect on 8d3cfac8:** nominal bolts 17 -> 5, because bolts had been guessed through the duplicate plates.
- **Hole cuts are checked** (data-3 Nantucket 7.312, 9 jobs, `standard_constructionerror`: stage 2 crashed, stage 1
  shipped).
  - The boolean returned an empty compound for 4 W16x100 / W14x82 beams with 34-38 web holes. BRepCheck accepts an
    empty compound, so the empty piece was written, and the bolt-hole pass then failed on its void box.
  - A cut must now keep a solid and 50-100 % of the volume. If not, the holes are cut one at a time; if any still
    fails, the piece stays uncut and its holes are reported not cut.
  - The bolt-hole pass and the stored-hardware lookup skip shapes with no geometry.
  - Nantucket 03393338: stage 2 now converts. 16,256 pieces, all 9,617 holes cut, weight 1.022, class 2 B (nominal
    bolts).
- **Local read-back runs, all valid:**

| job | (a) removed | (b) kept | solids | class |
|---|---|---|---|---|
| 8d3cfac8 | 3 | 0 | 323 | 2 B |
| 6eeedc27 | 0 | 2 | 164 | 1 A |
| AGNEWS-R | 58 (56 + 2) | 21 | 1,544 | 2 B |
| ca1a958a | 56 (55 + 1 EC-27) | 19 | 3,202 | 2 B |
| 1f9bb631 | 8 | 4 | 189 | 1 A |

## v5.5.10-rc (v5.5.9 + read-back repair reaches every written part; same CLI) — canary

- **Problem:** the read-back repair named the parts that read back invalid, but parts written as placed copies were
  never rewritten or left out. Those are world-built rods, parts that failed the assembly check, flat-mode pieces and
  bolts. Data-3 7.516 0535bdbb / 4c381a54 stayed class 0 in v5.5.8 and v5.5.9 with 7 / 3 such parts, all named
  RB1/2 rods on joists. Examples: JOIST #182 RB1/2 piece 20247 inst 5/6/12/13; JOIST #1895 piece 12130 inst 1.
- **Fix:** a part named by the repair is now left out in pass 2 whatever form it was written in. It is listed under
  skipped (`exact_solid_invalid_at_placement`) and counted in `invalid_parts_excluded`.
- **Pass 1 rewrites world-built rods** (special-primitive turned pieces) that read back invalid as the same rod built at
  the origin plus a placement, like v5.5.9's joists.
  - Local check: 200 RB1/2 rods at 0535bdbb's origin (about 62,000 in out) in random orientations. Built in world
    coordinates, 19 read back invalid; as a local part plus placement, 0 do.
- **New manifest section `readback_repair`:** lists every instance the repair rewrote (and the form used) or left out.
  It is present only when the repair acted.
- The repair log line now prints up to 20 names (was 5).
- **Local checks (Mac, light):**
  - Name matching tested against the exact names from both jobs' logs, plus the untyped Spectrum and METHODIST names.
    Leading-space labels match, and near misses do not.
  - AGNEWS-R with 3 rods and 2 exact pieces named:
    - no names: identical to v5.5.9 (1,546 shapes, same volume);
    - pass 1: 5 rewritten, all valid, same volume;
    - pass 2: 5 left out and listed (1,541 shapes). v5.5.9 left out only the 2 exact pieces (1,544).
- **Expected on the canary:** 0535bdbb / 4c381a54 leave class 0 (rods rewritten or left out and listed); controls
  identical.

## v5.5.9 (v5.5.8 + joist stand-ins as placed parts, member-index proofs; same CLI)

Regression (BOX-B, `--verify`, v5.5.8 -> v5.5.9):
- **Control:** GMS, AGNEWS-R, TYSONS, METHODIST and 19002 stage 1 are identical (class, valid count, top-level
  shapes, volume, weight).
  - `unique_parts` rises because joist stand-ins are now shared parts (GMS 797 -> 1002).
  - AGNEWS-T was not rerun (its download was incomplete; waived by the coordinator).
- **v5.5.8 confirmations on BOX-B:**
  - SOCORRO #3492 HSS5x2x5/16: exact_brep (v5.5.7: profile_fallback).
  - Spectrum: class 2 B, 16,215 of 16,215 valid.

- **Joist stand-ins are written as a local part plus a placement**, like exact pieces. Built directly in world
  coordinates, their web-bar cylinders lost precision far from the origin and read back invalid. Data-3 7.516
  0535bdbb: 140 bars of 67 of 220 joists, about 62,000 in from the origin.
  - v5.5.8 left those joists out after read-back (`invalid_parts_excluded` 60 and 61 on 0535bdbb / 4c381a54).
  - v5.5.9 writes all of them (195 / 203 joist stand-ins), and every joist reads back valid; nothing excluded.
  - Pieces, volume and weight are unchanged.
  - Both jobs stay class 0, for a separate reason that is unchanged since v5.5.8: 7 / 3 other parts read back invalid
    (RB1/2 rods on joist members, open surfaces), and the read-back repair does not match their names. Next item.
- **No member layout:** the converter now records why, from the member index and files themselves, as
  `index_proof`, class 3 C, then fails as before:
  - `corrupt_index`: mem_idx bytes are random or foreign (entropy > 7.5 of 8). Data-3 18e77755 Forsyth County 7.331:
    8.00, and member files with a broken gzip header and text.
  - `unknown_layout`: anything else.
- **Untyped member index with member files** (no typed record, < 1 % non-zero bytes): the members' own files still
  hold their material blocks, so pieces are placed from them.
  - The members stay untyped: no section, no work line, no envelope. The manifest carries `index_proof`.
  - Data-3 SISD backups 7fa1c983 / e1304b91: failure -> class 1 A (3 exact pieces each).
  - 94b59c49 7.132: its one member file holds no material block -> class 3 C, 0 placements.
- Also lifted by v5.5.7's stub-member calibration: 6eeedc27 100 Binney Slab Arch -> class 1 A (164 exact pieces).

## v5.5.8 (v5.5.7 + repair stage for piece B-reps, read-back exclusions listed, grating / rod fixes; same CLI)

Regression (BOX-C, `--verify`, v5.5.7 -> v5.5.8):
- **Control:**
  - GMS, AGNEWS-R, AGNEWS-T, TYSONS, 19002: identical.
  - METHODIST: 31 more pieces exact (approx 98 -> 67), all valid, class 2 B.
- **DSCC 7.312:** W10x12 piece 5513 is `exact_brep` again (v5.5.7: profile_fallback).
- **Class lifts:**
  - IFC_MHP 7.708: class 2B -> 1A (approx 3 -> 0; 3 HSS6x4x1/2 pieces by the tube identity).
  - Revit_MHP 7.708: 1A.
  - 10 World Trade 7.619: 2B -> 1A (approx 23 -> 0; its open HSS surfaces now close as solids).

### Piece B-rep repair stage (rebased from the `_pfix` sds2-approx-pieces-7x patch, reviewer-confirmed)
- **Live regression fixed.** v5.5.4-v5.5.7 split keyhole / spike loops in every piece, which lost pieces that only build
  with the out-and-back edge (DSCC 7.312 W10x12 #5513, SOCORRO 7.425 HSS5x2x5/16 #3492).
  - `brep.solid(..., repair=True)` now first tries v5.5.3's passes: as stored, `conform()`, `drop_covered()`.
  - Only when all of these fail does the repair stage run. So every piece v5.5.3 builds is built as before.
- **The repair stage** uses only the stored faces; no face is added. In order:
  - the 7.6xx **first-vertex keyhole bridge**: `[4, 1, 0, 5, 6, 1, 4, 7, 8, 9]` is an outer ring with a bridge, not a
    loop plus a triangle (10 World Trade 7.619 HSS);
  - **cancelling edges stored once in each direction across all loops of a face**: bridges, spikes, and an inner ring
    along the outer ring (Kerman 7.619);
  - ring caps over hollow ends;
  - isolated faces, zero-width flaps and overlapping coplanar patches;
  - a 0.001-in weld.
  - `brep.REPAIR_MAX_FACES` (5,000) bounds it.
- **Negative stored weights:** some 7.1xx-8.0xx tables store the piece weight with a minus sign. A B-rep within
  0.98-1.02x of |weight| is accepted (47 of 47 such closed pieces, 14 jobs).
- **Tube identity:** a curved / sloped HSS / pipe whose recorded weight is wrong (IFC_MHP / Revit_MHP 7.708 HSS6x4x1/2)
  is accepted when all of these hold:
  - its wall (2 x volume / surface) is 0.85-1.1x the section's wall;
  - its thinnest extent is a side of the section;
  - its length (volume / area) lies between the chord less a side and a half circle;
  - **its local x extent is the table length (2 % + 0.05 in)**. The reviewer asked for this check; the patch lacked it.
- **Section-area identity:** v5.5.4's `_section_ok` already accepts by the area from the section's own job_mtrl
  dimensions. It stays the single section rule, and the patch's overlapping rolled / plate stock identity is not
  taken.
- **Manifest:** `brep_repairs` {repaired, weight_unvalidated, negative_weight}, and log counters
  `exact_brep_repaired / _weight_unvalidated / _negative_weight`.
- Expected lifts (review, against v5.5.6): IFC_MHP and Revit_MHP 7.708, 2B -> 1A.

### Read-back exclusions are always listed

- **Problem:** parts that the read-back repair (or v5.5.7's final budget pass) leaves out are listed as skipped,
  reason `exact_solid_invalid_at_placement`, with member / piece / instance. The label pattern needed a member type,
  so parts of members without one (" #<n> / ...") were dropped from the STEP without a skipped row.
- **Now:**
  - Those labels are parsed too, and anything unparsed is listed by its label.
  - New count `invalid_parts_excluded`, plus a class reason. These parts lower coverage (they count as not built);
    they never disappear silently.

### Grating / rods
- `grating._on_stored_face` tests the covering face with its holes. A tube end over a hole in a carrier plate is not a
  contact face, so it is no longer closed (that would add a face the source does not store).
- `_name_dia` reads the size up to the first non-digit that is not part of a fraction: 'RB3/4x12' -> 0.75 in (was
  3.0), 'RB1x6' -> 1.0.

Not taken (refuted by their reviews): `sds2-weights-failures` and `sds2-pieces-not-built` (`_nest_voids`).

## v5.5.7 (v5.5.6 + turned pieces checked against their mesh and SDS2's weight; same CLI)

- **Which pieces:** rods / studs / anchors built as cylinders from rings of vertices (`turned_local`, and the
  straight-rod guess).
- **New check:** they must be the piece. On both axes across the rod the vertices span at least the ring diameter (a
  full ring, not an arc), and the cylinders weigh 0.25-4x SDS2's weight. The band only catches gross errors, because
  weld studs come out at ~0.5x.
- **Otherwise:** the piece goes on to its own B-rep, or is listed as not built. It is never a wrong cylinder.
- **Pieces whose piece file is absent from the job:** skipped as `no_piece_file` instead of
  `no_usable_special_geometry`, and counted as `pieces_without_piece_file`. This is source data absent, not a
  converter failure, so they don't count toward the "> 5 % not built" broken rule. The class reason names them
  (class 2). Example: data-3 TARRIER NEW ALBANY 7.312, 904 BLT placements of 7 piece ids with no file.
- **Open steel surfaces (v5.5.4 `brep_open_surface`):** written as the unsewn face set. Sewn open shells read back
  invalid once placed (data-3 Spectrum: 31 of 265 open HSS tubes made the job class 0); face sets read back valid.
- **Read-back repair:** labels of members without a type start with " #". The repair compared them unstripped
  against the read-back names, which are stripped, so the "write as placed copy" and "leave out" passes never
  matched them, and invalid solids stayed in the STEP (Spectrum v5.5.3: 12). Both sides are now compared stripped.
- **Read-back time budget (`--verify`):** the read-back and its repair passes share `SDS2_VERIFY_BUDGET_S` (default
  7200 s; 0 = no limit).
  - A repair pass runs only if conversion + 2 read-backs fits in what is left. At most
    `SDS2_REPAIR_MAX_PASSES` (default 2) run.
  - If only a rebuild fits, a final pass leaves every still-invalid part out (reported as skipped) without
    re-checking. The read-back is then recorded as partial.
  - A read-back past the budget is stopped. The written STEP is kept, and the manifest records
    `readback: {partial: true, note, checked: false}` (graded without read-back) instead of the job timing out.
  - The preview stops at `SDS2_PREVIEW_TRIS` (default 3,000,000) triangles.
  - Why: 260 fleet timeouts hit 4 h after the STEP was written; 7.135 jobs ran 3 conversions plus 3 read-backs and a
    24.9 M triangle preview.
- **Calibration with stub member files:** some 7.2xx jobs have member files with no work point (140 / 846 B), so
  calibration failed with "member work points not found".
  - The 7.2+ families now fall back to the left end at 0x112 (the same in every 7.2-8.0 layout). The end-point and
    section searches still validate it.
  - The 2,494-byte fixed layout now also covers 7.2xx other than 7.245, with the section at 0x1D4 (7.243 Binney; 7.221
    found by search).
  - Example: data-3 5eed44fe 7.221, failing -> 5,127 members with sections.
- **Why:** data-3 7.331 jobs had 'RB59' pieces, curved shells 59 x 25.5 in across and 3,405 lb, which the rings along
  one axis turned into 186,000 lb rods (RB family 33x SDS2's weight on 262 v5.5 jobs; RB79.2, 7.522, the same).

- **Regression (BOX-C, v5.5.6 -> v5.5.7):**
  - Control: GMS, AGNEWS-R, AGNEWS-T (repair pass 1 fixes its 2 parts), TYSONS, METHODIST, 19002: identical.
  - 866f2a7a (7.522, RB79.2): class 0 -> 2; RB family 28.1x -> 1.00; job weight 1.66 -> 1.008.
  - ebce209f (7.331, RB59): job weight 4.22 -> 1.014.
  - TARRIER NEW ALBANY: class 0 -> 2, its 1,136 no_piece_file pieces named.
  - 5eed44fe 7.221: failure -> 5,127 members (class 3 C, members only; the member files hold no pieces).
  - AGNEWS-R with a 15 s budget: read-back partial, class 2.

## v5.5.6 (v5.5.5 + bar grating and rods from SDS2's stored data; same CLI)

Merged from the `_pfix` sds2-grating-cylinders patch (base v5.5.3, applied cleanly on v5.5.5). Its README has the
decoding notes and per-job tables. Details are in `decode/grating.py`.

- **Bar grating / treads (`GR` / `GT`):**
  - Bearing bars, bands, carrier plates and nosing come from the piece's own faces.
  - Open bar tubes are closed only where their stored end outline lies on another stored face (a contact face that
    disappears in the union). No open mesh is filled.
  - Cross bars are the stored cross-bar outlines extruded by the grating record's cross-bar depth.
  - Accepted when the weight is SDS2's (3 %), or for a cut panel when the weight per plan area is the stock's.
    Otherwise the tagged panel stays.
  - Tagging (owner decision): a built grating is exact when it weighs SDS2's weight within 3 %, or when it is a cut
    panel whose outline is the stored faces (no partition cells). The bars come from SDS2's faces and the cross bars
    from SDS2's stored outline times the record's stored depth, like members from their section and length.
  - Otherwise it is tagged `[approx: cross bars built from SDS2's stored cross-bar outlines and the grating record's
    cross-bar depth ...]`, stand-in type `grating_crossbars_from_record` (class 2).
  - Before, it was a solid panel at 5-10x SDS2's weight.
- **Rods / studs / anchors:**
  - Straight rods whose rings are off the piece axes get exact cylinders on the axis of their own end caps. Every
    vertex must be on the named diameter, and the weight must be 0.75-1.33x SDS2's.
  - Bent / hooked rods use their own B-rep (vertices within 0.002 in merged) instead of a straight-rod guess.
- **Manifest:** new `grating` and `rods` sections.
- **Control regression (BOX-C, v5.5.4 -> v5.5.6):**
  - GMS, AGNEWS-R, TYSONS, 19002: identical.
  - AGNEWS-T: 6 more pieces exact (rods).
  - METHODIST: 58 more pieces exact (approx 156 -> 98).
  - Classes unchanged; every read-back part valid.

## v5.5.5 (v5.5.4 + proof for jobs with piece files but no member file; same CLI)

- **Which jobs:** 159 data-3 jobs fail with "no member files" although they hold piece files (1 to 48,498). They are
  seed / library / emptied jobs, plus 4 DWF imports whose member file is gone.
- **Why nothing is placed:** SDS2 keeps every placement in a member file, so none is stored. Nothing is placed.
- **What v5.5.5 records:** `empty_job_proof.unplaced_pieces_proof`, with
  - a mem_idx census: non-zero bytes and the typed records still in the index. Records without a member file are
    stale entries, and that is noted.
  - piece-local geometry evidence: median centre distance from the origin and median piece size, over up to 400
    piece files.
  - a piece-table summary.
- **Class:** 3 C, with the class reason "pieces without placements: ... no placement is stored".
- **Survey of the 159:**
  - Every job has its pieces in piece-local coordinates (centres within a few inches of the origin).
  - 133 have an all-zero mem_idx; 26 keep a few stale typed records (BEAM / COLUMN / AnchorRod / DWF Import) with no
    member file.
- **Test (BOX-C):** 13 of them, including VCUCH (48,498 piece files), 4 DWF and stale-index jobs, and seeds. All
  give class 3 C with the proof. Typical piece-local medians: centre 0-9 in from the origin, size 14-23 in. A normal
  job (AGNEWS-R) is unchanged.

## v5.5.4 (v5.5.3 + more of SDS2's own piece B-reps, CSU-type jobs, NC1 holes opt-in; same CLI + `--nc1`)

Regression (BOX-C, `--verify`, read-back and repair on; v5.5.3 -> v5.5.4):
- **Control:**
  - GMS, AGNEWS-R, AGNEWS-T, TYSONS: identical.
  - METHODIST: 18 more pieces exact (approx 174 -> 156), 5 of them open surfaces; all 12,386 read-back parts valid;
    class 2 B.
  - 19002-IMS6 stage 1: identical.
- **7.3xx fallback jobs (approximate pieces):**
  - PSU Music Hall: 2,329 -> 1,430.
  - Chester Trench: 1,132 -> 759.
  - S-Park: 1,909 -> 1,685.
  - Loudoun: 1,390 -> 1,370 (most of the rest have no piece file).
  - Classes unchanged, all read-back parts valid.
- **CSU 15-027:** calibration failure -> class 2 B, 14,510 valid solids.
- **North Urban with `--nc1`:** holes_from_nc1 on 182 placed pieces (320 holes in the piece files), all valid, class 2
  B. Without `--nc1` the output is unchanged.
- **Unchanged:** Edge_West, jfkf.

### More pieces use SDS2's own B-rep instead of an approximation
On the 7 data-3 7.3xx jobs with the most fallback pieces, 4,515 of 9,910 approximate instances are now exact. 1,548
of the rest have no piece file in the job (source absent).
- **Section validation:** a rolled piece's B-rep is accepted when it is its own section over its length.
  - The test: the two smaller extents equal the section's depth / width; the volume over the length equals the area
    computed from the section's own dimensions (0.75-1.3), or 0.6-1.6x its weight per foot.
  - Used when SDS2's piece weight is missing or disagrees: user-added sections carry wrong weights, e.g. UOM
    L1x1x3/16 at 0.354 lb/ft, S-Park HSS1 1/2x1 1/2x14GA at 3.55 lb/ft.
  - Count: `pieces_validated_by_section`.
- **Unreadable piece-table entries:**
  - Applies when the slot holds no piece record: text such as JSON in data-3 SUAC 7.331, or sizes like 1e243.
  - When the piece file holds a closed, valid solid of plausible size, it is written instead of an approximation
    built from garbage dimensions.
  - Tag: `[approx: SDS2's stored B-rep, not validated: the piece-table entry is unreadable]`; stand-in type
    `brep_unvalidated` (class 2).
- **Hollow-section ends (7.1xx draft):**
  - Spikes (a -> b -> a) and keyhole loops are split.
  - A full disk that repeats a ring face's outer loop is dropped.
  - Example: Chester Trench PIPE 1 1/4 STD, 259 instances.
- **Open rims:**
  - Applies to a body whose only defect is open rims (tube ends, a missing face), when its extents are the piece's
    own section / table size.
  - It is written as the open surface SDS2 stores (sewn shell, or the unsewn face set when the shell fails BRepCheck),
    never closed or filled (owner rule for open meshes).
  - Tag: `[approx: open surface as stored by SDS2 (its rims are open), not a closed solid]`; stand-in type
    `brep_open_surface`.
  - Not counted in the steel tally; no bolt-derived holes.

### Jobs with a few unusable member records (data-3 CSU 15-027 7.312)
- The fixed-layout fallback now accepts a slot family when up to 10 % of the structural records have non-finite or
  absurd end points, as long as every section is valid. Before, one bad record failed the whole job with "member
  work points not found".
- Those members are listed as skipped, reason `member_end_points_unusable` (stage 1: CSV note). They hold no pieces
  and don't count toward the "> 5 % not built" class rule.
- CSU: 9,640 member solids (stage 1); 14,510 placed solids, all valid after repair, class 2 B (stage 2).

### `--nc1 <dir|zip>` opt-in: holes from the job's own NC1 / DSTV files (decode/nc1.py)
- **Matching rule:**
  - The NC1 order line equals the job folder name (a batch "_<6 hex>" suffix is ignored; `SDS2_JOB_NAME`
    overrides).
  - The NC1 piece mark equals the member's decoded mark: mem_idx i16 at the section field + 4 -> pcm/pcm_list
    record. Validated on Binney: 3,944 of 3,944 shared marks agree with the IFC.
  - Every member with that mark has the same main piece.
  - The length is within 3 mm and the profile name is equal.
  - The part is code I with a W profile. Angles and other shapes are never cut.
  - If several NC1 files for one mark disagree, nothing is cut.
- **Where a hole is cut:**
  - Round holes only, at the stored position and diameter.
  - Only on a face where another NC1 hole matches a decoded hole; that hole gives the entry point, axis and depth.
  - Only where every decoded hole on the face is one of the NC1 holes.
  - Never within 25 mm of a decoded hole.
- Tagged `holes_from_nc1` (stand-in type, class 2); the manifest has `nc1_opt_in` stats.
- Dry run on 9 jobs: 2,176 W parts matched strictly; 713 holes on 358 pieces qualify (North Urban 320, South Urban
  376); 91 % of strict NC1 holes were already in SDS2's piece files; Cats Rail: 0.

### Read-back
- The preview draws the largest parts anywhere when nothing is drawable near the model centre (data-3 KJL). It
  stays capped at `SDS2_PREVIEW_MAX`.
- The manifest read-back now records `surfaces`.

## v5.5.3 (v5.5.0 + three fixes, released together; same CLI)

Released as one version (owner: avoid three re-run waves). The fixes are listed as 5.5.1, 5.5.2 and 5.5.3.

Regression (BOX-C, `--verify`, read-back and repair on; v5.4.1 -> v5.5.3):
- **Control:**
  - GMS, AGNEWS-T, METHODIST: identical.
  - AGNEWS-R: 1,681 -> 1,546 read-back solids. That is 45 nominal bolts on stored BLT hardware (3 solids each).
  - TYSONS: 6,990 -> 6,885 (35 such bolts).
  - Classes unchanged, every read-back solid valid, weight ratios unchanged.
  - 19002-IMS6 stage 1: identical to v5.5.0.
- **Evidence:**
  - Edge_West 7.711: class 0 broken -> class 2 B, 6,606 -> 8,052 solids (the 1,504 SB1/2 balusters are written).
  - 888 Boylston: 94 couplers / bent rebar no longer skipped, 15,654 -> 15,748.
  - Befor North: 276 of 276 nominal bolts no longer written over the stored hardware, 7,521 -> 6,693.
  - jfkf: 70 -> 694 reference parts (624 open surfaces).
  - DFGH 7.720: calibration failure -> class 2 R, 935 parts.
  - Reference jobs 0965ed04 / 0e6cc241 (class 1 R): identical.

### 5.5.3 Reference models (DWF / IFC imports)
- **Calibration:** a job whose only member is an imported reference model failed with `mem_idx: too few members to
  calibrate (0)` in the 3,204 / 3,404 / 3,600-byte slot families (7.5xx-8.0xx). The sparse layout now takes the type
  offset from the import-kind marker (`DWF Import`, `IFC Import`, `SDNF Import`, `DGN Import`).
  - `DWF Import` sits at slot - 256 (3,404) or slot - 260 (3,600).
  - The `ReferenceModel` string near the slot end is a model name, not the type.
  - `REFERENCE MODEL` / `Reference Model` are recognised reference types.
  - Example: data-3 DFGH 7.720 went from a calibration failure to class 2 R with 935 parts.
- **Open shells that fail BRepCheck** are no longer dropped (v5.2-v5.5.0 skipped them as
  `reference_part_no_closed_brep`).
  - The stored faces are written as an unsewn face set: a compound of individually valid planar faces, never filled
    or closed.
  - Tag: `[reference: ... open surface (stored faces, not sewn), not a closed solid]`. New manifest count:
    `reference_face_sets`.
  - Example: data-3 jfkf 7.331 went from 70 parts (624 placements left out) to 694 parts (624 open surfaces).
- A reference model whose placement blocks carry no piece id stays class 3 R with that proof. Data-3 tg 7.619:
  6,406 blocks, and its 1,647 pieces are in local coordinates, so nothing can be placed without inventing positions.
- **Read-back (`--verify`):** an open-surface part counts as one placed part. Before, it counted one leaf per shell
  or face (jfkf: 64,971). A new line reports `open surfaces (reference parts, no volume): N`. The `with solids: ...;
  BRep valid: ...` line is unchanged, and `surfaces` is added to the read-back result.

### 5.5.2 Stored bolt hardware: no bolt solid on top
- Where SDS2 stores a bolt's own hardware (BLT head / nut / washer pieces, written as exact B-rep), no bolt solid is
  added on top. This applies to both nominal and SDS2-record bolts.
- **Test:** a BLT hardware piece centred on the bolt axis (within 0.3 d, at least 0.1 in), between d + 2 in before
  the head and d + 2 in past the grip.
- **Before:** data-3 Befor North had 276 of 276 nominal bolts written over the stored hardware (the audit found 618
  jobs exposed).
- The bolt still drives bolt-derived holes. New manifest count: `bolts_on_stored_hardware` {sds2, nominal}.

### 5.5.1 Bars and rebar no longer dropped as "absurd extent"

- **Root cause:** `_absurd()` received a shared exact part as a `("shared", solid, placement)` tuple. That happens on
  the special-piece path when the exact B-rep fallback is used. The bounding box of a tuple raised, and an exception
  counted as absurd. So every exact square/round bar, rebar and coupler on that path was skipped as
  `absurd_extent_corrupt_source_geometry`: 5,076 pieces on 13 jobs (v5-v5.5.0). The rule itself was right.
- **Now:**
  - A shared part is measured on its local solid; a rigid placement keeps its size.
  - Only solids larger than ~3 miles are dropped. No stored length or section is that large.
  - These pieces keep their table kind (`other`, ...) instead of `fastener`. Studs, rods, anchors and bolts are
    still `fastener`.

## v5.5.0 (v5.4.1 + joist regression fix; same CLI)

- **Joist designation parser:** it now knows DSLH (deep super long span), plus CJ / JG.
  - v5.2-v5.4.1 did not, so joists whose record has no depth (7.7xx boost records store d = 0 for joists) lost their
    depth and wrote no solid, silently. On data-3 19002-IMS6 (7.720) that was 50 JOIST 52DSLH / 64DSLH members:
    v5.1 drew them, v5.2-v5.4.1 did not.
  - Now: designation-derived open-web stand-ins with the designation's depth (stage 1: 3,283 -> 3,333 member solids,
    = v5.1).
- **No silent drop:** a joist that still cannot be built (no depth anywhere) is reported.
  - Stage 2: a skipped row with reason `joist_without_depth`.
  - Stage 1: the members CSV note and a "joists not built" count in the log.
- Regression (BOX-C, `--verify`, read-back + repair on):
  - Control jobs GMS, AGNEWS-R, AGNEWS-T, TYSONS, METHODIST: identical to v5.4.1 (manifest counts, class, read-back
    solids all valid, total volume).
  - 19002-IMS6 stage 1: placed solids 4,652 -> 5,367, all valid; member solids 3,283 -> 3,333; 988.7 -> 1,024.1 t.
    The 50 joists use the DLH-series estimate (30 lb/ft, spans 14-69 ft). v5.1 drew them with a K-series estimate
    (6.3 lb/ft, 8,540 placed solids, 995.8 t). Both are designation-derived stand-ins (class 2), never class 1.
- Scan of all data-3 SDS2 outputs for solid drops between labels (625 job-labels, 23 jobs with more than one label):
  this job is the only one.



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
