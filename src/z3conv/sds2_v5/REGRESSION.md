# SDS2 → STEP v4 → v5 / v5.1 regression report

**Builds compared**
- v4 = `sds2-step-pipeline-v4-candidate.zip` (sha c5b65d27…), the build used for data-4 and Disk-2 run 2.
- v5 = `sds2-step-pipeline-v5.zip` (sha 592c1d4f…).
- v5.1 = `sds2-step-pipeline-v5.1.zip` (sha 8f74f449…).

**How it was measured**
- Each job was converted with the fleet command: `sds2_to_step.py <job> -o X_stage2.step --stage 2 --verify`.
- The results were then measured with `qa/v5check.py`, which reads the STEP back with OCC XCAF and rebuilds the truth from the job's own data.
- The separate `verify/` package the FIX documents refer to is not in either zip, so its metrics (M1, M2, S3, G4, G5, HSS faces) were re-implemented here.
- G5 is reported two ways:
  - **faces:** against the vertices that the piece's own faces use (the true geometry);
  - **records (EC-45):** against every vertex record with the verifier's stray-point rule.

**Where the jobs ran**
- Local Mac: Greenwood, Binney stage 1, CHOWNS, defaultAdapt, the crash jobs, and the jobs that exercise the v5.1 fixes.
- Box 2: v5 (r2 code) and the v4 baseline on 41 data-4 jobs plus Binney and Greenwood.
- Box 3: v5.1 on the same set plus 8 jobs from the 2015.25 training `jobs.7z` (7 reference models, 1 empty job).

## 1. Per defect, using the FIX documents' metrics

| # | defect (FIX item) | metric | v4 | v5 / v5.1 |
|---|---|---|---|---|
| 10 | angle legs swapped | Greenwood G5 angles within 0.1 in (faces) / legs swapped | 160/160, 0 swapped | 159/159, 0 swapped |
| 10 | (approximate builder, 6.336 CHOWNS, no face topology) | angles: y/z cross-section agreement / legs swapped | 2,030: 100 %, 0 swapped | 1,991: 100 %, 0 swapped (95 % on all 3 extents; the rest are length trims, not legs) |
| 2 | PLG / WPS / WBX | Binney stage-1 M1 median | PLG 1.000 (43), WPS 1.005 | unchanged |
| 2 | (robustness) | jobs aborted by `ValueError: built-up dimensions…` | data-3 BG PODIUM_Job ×3, Boston_Garden_Checkers | 0: name dimensions, then weight-sized flanges tagged `[approx]`, never class 1 |
| 3 | HSS / pipe hollow | HSS faces median / hollow share | Greenwood 42 / 100 %; CHOWNS 10 / 100 % | same |
| 2 | round HSS 1.19× | ROUND M1 median, Binney stage 1 / Greenwood stage 2 | 0.996 / 0.996 | 0.996 / 0.996 |
| 11 | HSS orientation / extent | Greenwood HSS G5: faces / records (EC-45) | 100 % / 92.7 % | 100 % / 92.7 % |
| 13 | stray vertex records | G5 extent > section + 1 in | 0 | 0 (approximate builders now fit face vertices only) |
| 6 | skipped placed pieces | Greenwood | 28 skipped (all phantom NaN blocks) + 1 NaN placement in STEP | 0 |
| 6 | | Binney | 597 skipped + **140 NaN placements written** (700 STEP syntax errors, 140 unresolved references) | 0 phantom; STEP reads back with 0 errors |
| 6 | | CHOWNS (bent plates over 5×) | 33-34 skipped | 0 (34 tagged slab stand-ins) |
| 6 | | TYSONS 7.720 joist pieces | 1 skipped + 20 vertex boxes | 0 (21 designation-derived open-web joists, tagged) |
| 12 | piece written for two members | G4 introduced by converter | Greenwood 3, CHOWNS 44, box set 196 in 17 of 43 jobs | 0 (logged as `also_on_member`) |
| 4 | repeated solid names | S3 duplicate names | 0 (inst counter already in v4c) | 0 |
| 1 | joists as solid blocks | Greenwood M2 solid-block share (stage 1 and 2) | 205/205 = 100 % (mass 196× SDS2's placeholder weight) | 0 % (open-web, 4.0× SDS2's 2.5/5 lb/ft placeholder = SJI typical weight) |
| 5 | bent plates 0.41× | BPL M1 median, CHOWNS (approximate) | 0.919 | 0.919; exact path unaffected |
| 8 | holes | holes cut (exact pieces) | Greenwood 347, Binney 110,784 | same; also cut into approximate pieces when decodable |
| 9 | stage-1 work-line lengths | by design | — | documented |
| 7 | IFC recall | E1 | not re-measured | not re-measured (no IFC alignment in this tool) |

Weight check, STEP steel vs SDS2 piece weights:
- Greenwood 1.021 → 1.021.
- CHOWNS 0.989 → 0.989.
- defaultAdapt 0.992 → 0.992.
- Total model volume on Greenwood fell from 4,002.7 t "as steel" to 869.6 t, because the joist blocks are gone.

## 1b. Data-4 test set aggregates (box 2: checker on v4 vs v5 r2 STEPs)

v4 has 31 jobs with STEPs and v5 r2 has 33. The v5 r2 set adds AMOL and ANUSHA, which v4 crashed on, and v5 r2
converts more members on the others. r2 lacks the v5.1 / v5.2 fixes.

| metric | v4 | v5 r2 |
|---|---|---|
| G4 converter-introduced duplicates | 215 | 42 (v5.3 grid fix: AGNEWS-R 16 → 2) |
| G4 SDS2-twin duplicates (kept) | 490 | 492 |
| S3 duplicate names | 0 | 0 |
| joists written as solid blocks | 1,274 of 1,275 | 0 of 1,322 |
| HSS hollow (≥ 10 faces) | 8,247 / 8,247 | 8,238 / 8,238 |
| G5 angles within 0.1 in (faces) / legs swapped | 14,588 / 14,589, 0 | 18,431 / 18,431, 0 |
| G5 W | 14,667 / 14,675 | 15,764 / 15,771 |
| G5 HSS | 8,158 / 8,163 | 8,154 / 8,154 |
| G5 PL | 21,915 / 22,074 (99.3 %) | 23,540 / 23,545 (99.98 %) |
| G5 C / ROUND / BPL / WT | 1,331/1,336, 3,722/3,726, 1,501/1,504, 481/481 | 1,336/1,336, 3,685/3,688, 1,502/1,506, 481/481 |
| G5 by the verifier's raw-record rule: HSS / ROUND | 88.0 % / 18.1 % | 87.9 % / 18.1 % (unreferenced reference records; not a STEP defect) |

Binney (v5 r2, converter tally; the 2 GB STEP was too slow to check in this window):
- skipped 0 (v4: 597, plus 140 NaN placements);
- 137 converter duplicates removed;
- 110,391 piece-file holes plus 452 holes on approximate pieces cut;
- steel 1.016;
- by weight: W 1.026, HSS 0.998, L 0.959, BPL 1.009, ROUND 0.930 (SDS2's own faceted pipe).

## 2. Failure classes fixed (data-4 / data-3 evidence)

| failure (v4) | jobs | v5 / v5.1 |
|---|---|---|
| invalid solid(s) after read-back → kit rejects the job | 13 data-4 (AGNEWS-T, METHODIST ×4, Alcon, FERNDALE, MORROW ×2, Cleburne, Uconn ×2, BRIDGE PARK, AGNEWS-L) | read-back repair pass (v5.1). METHODIST: 12,385/12,386 → 12,386/12,386 |
| OCC core dump on NaN member end points ("other", rc 139) | ANUSHA_JOB, AMOL_Job (7.135) | converted: 39,254 and 12,904 valid solids, class 2 |
| ZeroDivisionError in plate_outline | data-3 vbf2er, NVX, dddd (7.4xx), Seaport L4_Job (7.619) | guarded |
| `ValueError` built-up profile | data-3 BG PODIUM ×3, Boston_Garden_Checkers (7.331) | never raises |
| "too few members" with an ambiguous mem_idx slot size | Tarrier 7.323 | converted (2 members, class 3: a seed job) |
| "too few members" with no member files at all | data-4: 11950_3, 28014, 1442_NORTH_SHORE, Example, Job ART IRON, John_Bowman, Cives_7.135; data-3: 19 of 71 2015.25 sandboxes, 7.331 jh7 / NNB / … | genuinely empty: manifest with `empty_job_proof`, class 3 |
| 0 solids / "STEP write failed" / "no members", one *DWF Import / ReferenceModel* member | data-3: about 50 of 71 2015.25 jobs and most 7.331 `jobs.7z` jobs (hyf, pp3, uuii, …) | v5.1: reference parts from SDS2's stored B-rep, corpus R |
| steel 0.19-0.22× (one 447,816 lb BPL240x240 record) | DOWCORNING 7.039 ×2 | listed as a dominant outlier; ratio without it 1.016, class 2 |
| steel 1.30× (grating "GR" weighed as open mesh) | GM M5 FLINT 7.312 ×2 | GR grating tagged and kept out of the tally (v5.1) |
| STEP with NaN placements (syntax errors on read-back) | Greenwood, Binney | none |

## 3. Per job (box 2: v5 r2 build vs the v4 baseline; version column)

- `regression/jobs_table_v5r2_vs_v4.md`: per job, with a version column. It compares v4 (box 1 / box 2 runs) with the
  v5 r2 build on box 2. The r2 build predates the v5.1 fixes: read-back repair, GR grating, joist pieces, outliers
  and reference models.
- `regression/version_table_v5r2_vs_v4.md`: the version matrix.
- `regression/jobs_table_v51.md`: v5.1 results from box 3, as far as the box had got when this report was written.
  Everything lands in `s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/v5dev/regress3/` (per job: log,
  manifest, pieces / skipped CSV, metrics.json). The box writes `DONE` there and shuts down.

## 4. Visual checks

- `report/gms_v5_joists.png`: Greenwood joists read back from the v5 STEP as open-web joists (double-angle chords, round-bar web).
- `runs/v5/*_preview.png`: the full-model previews written by `--verify` for every converted job.

## 5. What remains / open findings

- **Main-member bolt holes (FIX item 8):** see section 7. The member-file blocks are bolt records, not holes; main
  members store no hole records. v5.4 cuts bolt-derived holes where a decoded bolt and a coaxial decoded diameter
  exist. Single-ply connections stay undrilled and are listed. Greenwood NC1 still shows 0 of 90 holes on matched
  placed parts.
- **E1 (IFC recall):** not measured here; assigned to the workflow agent.
- **Reference-model import variants:**
  - hyf style: piece id at +0x6C; parts written.
  - Open meshes: written as shells in v5.2.
  - duct-l5 / pp3: no piece link in the data; class 3 R with proof.
- **6.3xx jobs:** no face topology; everything approximate and tagged (class 2).
- **Joists in 7.0-7.6 jobs:** derived from the designation; class 2 by rule.
- **Copes on approximate pieces:** not modelled; tagged.
- **v5.1 full-set regression incomplete:**
  - Box 3 (i-03cfb4e1a37db698c) stopped answering SSM and stopped uploading at about 22:20Z (CPU about 4 %,
    presumably memory exhaustion with Binney and large reference meshes in parallel). It was terminated after its
    8 completed jobs (see `regression/jobs_table_v51.md`).
  - Box 1 shut itself down via SSM after recovering. Box 2 finished and terminated itself.
  - The v5.1 / v5.2 / v5.3 behaviour was verified locally on the 15 jobs listed in section 2 instead. The builder's
    re-run of affected jobs is the full-scale regression.

## 6. Releases

| zip | sha256 | content |
|---|---|---|
| sds2-step-pipeline-v5.zip | 592c1d4f… | the v5 fixes (section 1) |
| sds2-step-pipeline-v5.1.zip | 8f74f449… | + reference models (corpus R), read-back repair, GR grating, dominant outliers, joist pieces, no class-1 tolerance, empty-job proof |
| sds2-step-pipeline-v5.2.zip | f2d05d38… | + open reference meshes as shells, unlinked reference variant → class 3 R, seed jobs → class 3 C, joist depth from designation |
| sds2-step-pipeline-v5.3.zip | see CHANGES | + duplicate grid 0.1 in (G4 AGNEWS-R 16 → 2) |

## 7. v5.4: bolt-derived main-member holes (validated on BOX-C, i-0d97427e58ca5ef28)

- **Finding:** the member-file 658-B "hole blocks" are SDS2 bolt records. Main members store no hole records;
  Greenwood main-member piece files carry only 0-diameter markers.
- **NC1 counting fix:** NC1 BO lines with a 0 diameter are punch / scribe marks, not holes. Greenwood NC1 has 287
  real holes on the 26 parts that match by profile and length, not 392. Only 12 of those parts are placed in this
  model snapshot; the fab package is a later sequence, so the other 14 match stale, unplaced pieces. Those 12 placed
  parts carry 90 NC1 holes.
- **Greenwood NC1 result (12 placed parts, 90 real holes):**
  - v5.3: 0 matched / 90 missing / 4 extra.
  - v5.4: 0 matched / 90 missing / 4 extra. Its 12 derived holes sit on 3 pieces that are not among the
    NC1-matched parts.
  - Greenwood's beam holes are single-ply connections (one clip angle or shear tab against the web) with no SDS2 bolt
    record: 4 records in the job, 394 nominal bolts. By rule they are not extended. They are listed as
    `mating_holes_not_stored` and keep the job in class 2.
- **Derived holes cut (v5.4):** Greenwood 12, AGNEWS-R 16, AMOL 12, TYSONS 39, AGNEWS-T 104, METHODIST 71,
  DOWCORNING 0.
- **Binney 7.243:** 2,904 derived holes on 308 pieces from 173,813 bolts (108,507 SDS2 records).
  - 21,228 bolt-to-piece crossings are not cut because no ply has a coaxial decoded hole, so the diameter is unknown.
  - 19,057 decoded single-ply holes are not extended into their mating piece.
  - Conversion: 1,708 s, 0 skipped, steel 1.016, 240 converter duplicates removed. The AGNEWS-T derived-hole part that read back invalid was fixed by the repair pass
  (5,786 / 5,786 valid).
- **Grading:** Binney has no NC1 (its 1 GB project archive has no CNC folder) and its SDS2 IFC has no openings, so
  derived holes cannot reach the ≥ 99 % NC1 bar. They stay a class-2 stand-in type, `holes_derived_from_bolts`,
  with per-piece counts in the manifest.
