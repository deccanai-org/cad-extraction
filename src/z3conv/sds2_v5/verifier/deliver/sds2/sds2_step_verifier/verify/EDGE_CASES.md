# SDS2 → STEP edge cases and the checks that guard them

Every case below was actually hit while decoding 50_Binney (7.243), Greenwood Middle School (7.312) and
Sheriff's Office (7.425), or while probing the 2,474 Disk-2 archives. "Guard" is the verifier check that
turns the case into WARN/FAIL; `selftest` lists the deliberate defect that proves the guard fires.

| id | edge case | seen in | guard | selftest |
|---|---|---|---|---|
| EC-01 | `mem_idx` size fits no known slot size (256-B header + n×slot; 2494 = 7.2xx, 2944 = 7.3xx, 2976 = 7.4xx) → unknown layout | design | D1 | – |
| EC-02 | `main/jsetup` version disagrees with the slot-size family (copied/renamed jobs, mixed versions) | design | D1 | – |
| EC-03 | auto-calibration picks a slot size that is not a known one | design | D1 | – |
| EC-04 | version family not supported by the decoder (7.4xx, 7.5xx, 7.6xx, 2015.x) | Sheriff 7.425 | D1 (FAIL, pre-conversion gate) | – |
| EC-05 | piece decoding validated only on 7.2xx; 7.3xx pieces unverified | Greenwood | D1 (WARN for stage-2) | – |
| EC-06 | `job_mtrl` is not 510-B records (7.425 uses 390-B records) | Sheriff | D2 | – |
| EC-07 | shape-dimension offset shifted → W18x35 no longer 17.7 × 6.0 × 0.425 × 0.3 | design | D2 (AISC spot check, 12 shapes) | – |
| EC-08 | member-type string offset wrong → no structural members | design | D3, D4 | – |
| EC-09 | section field offset wrong: one candidate (0x1E2 on 7.312) gave W44x290 for *every* member | Greenwood | D3 (top section > 80 % ⇒ FAIL) | – |
| EC-10 | many members without a section (Ref Points, MISC, zero index) | Binney | D3 | – |
| EC-11 | end point read from the wrong offset (0xD0 in the mem record) ⇒ 72 % zero-length beams | Binney | D4, G1 | – |
| EC-12 | garbage / huge coordinates from mis-aligned doubles | design | D4 | – |
| EC-13 | columns not vertical (axis field wrong) | design | D4 | – |
| EC-14 | roll angle NaN / huge (reader sanitises to 0 — raw value checked separately) | Binney | D4 | – |
| EC-15 | stray scratch members placed far from the building | Binney preview | D5, G2 | scattered |
| EC-16 | STEP writer drops or adds solids vs the manifest | design | S1 | drop 15 % |
| EC-17 | invalid / open / zero-volume B-rep (degenerate profiles, zero-length prisms) | design | S2 | – |
| EC-18 | solid names do not trace back to SDS2 member / piece ids | design | S3 | duplicates |
| EC-19 | unit error: inches written as mm (or header unit wrong) | design | S4, M1, G1 | unit error |
| EC-20 | wrong section on a member (section table / index off by one) | design | M1, E2, E3 | wrong section |
| EC-21 | wrong member length | design | G1, E2, E3 | – |
| EC-22 | beam hung on its centreline instead of top of steel (8.85 in error on a W18) | Binney calibration | G1, E1 | TOS error |
| EC-23 | vertical members' reference axis X vs Y (columns rotated 90°) | Binney calibration | G1, E1 | web rotated |
| EC-24 | solid placed away from its work line | design | G1 (strict ≥ 99.5 %), G2 | shift 6 in |
| EC-25 | piece placement uses M instead of Mᵀ (median error 8.8 in vs 0.2 in) | Binney pieces | G3, E1 | scattered |
| EC-26 | 658-B bolt/hole block mistaken for a 538-B material block | Binney pieces | G3 | scattered |
| EC-27 | main material written twice (header block + material block) | Binney pieces | G4 | duplicates |
| EC-28 | same job converted from two archive copies (weekly backups) | Disk-2 inventory | G4 (per model), batch dedupe | duplicates |
| EC-29 | IFC in site coordinates (x ≈ 234,600 m) with a small rotation (−0.005°) | Binney IFC | E1 (RANSAC alignment) | mirror |
| EC-30 | connection pieces missing (stored with member id 0, e.g. MISC members; blocks interleaved with bolt groups) | Binney pieces | E1 recall, G3 | drop 15 % |
| EC-31 | section spelling differs between sources: `W30X99`/`W30x99`, `HSS12X12X.500`/`HSS12x12x1/2`, `L4x3 1/2x3/8`, `HSS2-1/2X…`, `PI8.625` vs round HSS | Greenwood KISS/NC1 | canonical names in E2/E3 | – |
| EC-32 | holes not modelled yet (NC1 lists 2,657 holes for 95 parts) | Greenwood NC1 | E3 reports, not graded yet | – |
| EC-33 | KISS / NC1 repeat the same piecemark across the full ABM and each fab package | Greenwood | E2/E3 dedupe by mark | – |
| EC-34 | open-web joists (24K4, 32LH06 …) written as solid blocks — 100–260× real mass | Greenwood | M2 (FAIL) | – |
| EC-35 | stage-1 members run on the work line, longer than the fabricated piece by the connection setbacks (HSS braces up to 28 in) | Greenwood | E2/E3 report tight vs loose recall and median excess length | – |
| EC-36 | pieces whose vertex table does not parse (tag byte 0x01 vs 0x02, zero-header files) are silently skipped | Binney pieces | S1 vs manifest, E1 recall | – |
| EC-37 | shared piece definitions: one `subm` used by many members (identical piecemarks) | Binney | M1 uses per-piece weight, not per-instance | – |
| EC-38 | 7.0/7.1xx and 2015.x jobs: layout never validated | Disk-2 inventory | D1 (unsupported ⇒ FAIL) | – |
| EC-39 | no ground truth for a job | most jobs | E-checks return **NA**, never PASS; `evidence` field drops to `mass` / `internal` | – |
| EC-40 | duplicate members inside the SDS2 job itself (6 in Greenwood) | Greenwood | G4 separates source duplicates from converter duplicates | – |
| EC-41 | a whole section family built from the wrong fields while the model-wide mass still passes (plate girders 0.39x, stage-2 HSS 4.8x solid) | 50 Binney | M1 per-family rule (>= 20 members, median outside 0.8-1.25 => WARN) | wrong section |
| EC-42 | built-up sections (PLG/WPS/WBX) keep flanges at +0x5A/+0x62/+0x6A/+0x72; +0x22/+0x2A are placeholders (1.0) | 50 Binney | M1 per-family (fix pending in converter) | wrong section |
| EC-43 | STEP writer builds a different solid than the decoded piece (angle legs swapped, HSS mis-oriented) | 50 Binney stage 2 | G5 independent rebuild (<= 0.1 in) | shift / wrong section / web rotated |
| EC-44 | connection material listed on the *other* member of the connection (e.g. shear tab owned by the beam, welded to the girder) | 50 Binney stage 2 | G3 accepts off-parent pieces only with IFC evidence (or touching another member when no IFC) | scattered |
| EC-45 | spurious vertex records hundreds of inches from the piece (mis-read doubles) | 50 Binney stage 2 | G5 rebuild trims vertices beyond the section size from the median | - |
| EC-46 | no mem/mem_idx in the extracted folder (not a 7.x job, or the archive stores only part of it) | Disk-2 run | D1 FAIL | - |
| EC-47 | section index field shifted / off by one: sections still look plausible (W18x35 -> W18x40) | design | D6 index vs main-piece-name agreement (rolled names only; plates excluded because the piece at +0xE8 is the member's first material) | wrong section |
| EC-48 | 7.0/7.1 store points and shape dims as 32-bit floats (1416-B mem_idx slot, 178-B job_mtrl records) and mem/<n> carries no work point | 7.135 | D1/D2 auto-calibration (f32 path, in-slot point-pair search) | - |
| EC-49 | joist-roofed / column-only jobs have too few BEAM members to calibrate the section field | 7.135 | calibration samples every structural type; joist designations count as valid sections | - |
| EC-50 | prototype / clipboard / empty jobs (0-2 members) | 7.209, 7.613 | D1 FAIL with an explicit "empty job" reason instead of a crash | - |
| EC-51 | job_mtrl layouts differ by version: 510-B BE f64 (7.2/7.3), 390-B LE f64 (7.425, 2015), 406-B LE (7.613), 470-B LE, 249-B LE, 178-B BE f32 (7.1) | Disk-2 run | D2 self-calibration (record size from name spacing; byte order, float width and offsets from AISC + W-name weights) | - |

## How to read a verdict

* **overall** — FAIL if any check fails, WARN if any warns, else PASS. NA is neutral.
* **evidence** — `external` (IFC / KISS / NC1 agreed), `mass` (only SDS2 weights agreed), `internal` (self-consistency only).
  Only `PASS` + `external` should be treated as ship-grade.
* **selftest** — every deliberate defect must be caught; an uncaught defect is listed as a blind spot for that job
  (usually because the job has no ground truth that could see it).
