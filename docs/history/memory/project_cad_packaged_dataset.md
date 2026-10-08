---
name: project_cad_packaged_dataset
description: CAD extraction packaged into the projpkg4 format, split 3d/2d — complete and verified 2026-09-24
metadata:
  type: project
---

Extraction finished at **3,620/3,620 archives, 0 failures**, then the output was
repackaged into the team lead's `projpkg4` format and split by geometry.

**Deliverable:** `s3://bim-proprietary-data/cad-disk-extract/dataset/main/{3d,2d}/` (bucket corrected 2026-10-06; not annotationprod)
2,477 projects · 26,046,695 files · 6.54 TB · 42,572,009 duplicates collapsed · 0 failures.
3d=216, 2d=2,261. Verified: 216/216 3d have `model/step`; 0/2,261 2d have any STEP; 40/40 structure checks.

**Routing rule:** 3d iff the archive holds any `.stp/.step` (native) OR any STEP our
DB1→STEP pass produced; everything else 2d, including the 8,484 unconvertible DB1s.
117 of the 216 3d projects qualify *only* because of our conversions.

**Unit = physical S3 archive folder, not ledger row.** 2,484 folders vs 3,620 ledger
archives: 622 Disk-2 archives stored zero new files (content dedup) so have no folder,
and their files live under whichever archive stored them first. Per-archive packaging is
NOT reconstructible from S3 for those — results carry SHA lists but not object keys.

**Format** (read from the LIVE projpkg4 tree, which differs from the draft spec in
`docs/PACKAGING_FORMAT.md`): `project.json` + `manifest.jsonl` +
`model/{step,ifc,db1,db2}` `drawings/{pdf,dwg,dxf,dg,dpm}` `fab/nc1`
`tables/{bom,abm,kiss,drawing_index}`. Paths are **flat, one dir deep**, 6-hex
disambiguator on collision. No `native/`, no `_derived/` — those were my invented names
and had to be redone.

Superseded first attempt still at `cad-disk-extract/packaged/` (~18M objects, wrong
format) — awaiting permission to delete.

See [[feedback_s3_bulk_copy_worker_design]] and [[reference_cad_iam_gaps]].

**Update 2026-09-26 (after STEP conversions + corrections):** 2,476 packages (probe package removed): 1,286 3d, 1,185 2d,
5 empty (archives with only non-asset files). 34,270 STEP rows. See [[project-db1-step-conversion]] for the passes.
