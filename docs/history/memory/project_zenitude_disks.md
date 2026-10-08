---
name: project-zenitude-disks
description: New source disks Zenitude-data-2/3 and Zentitude-data-4 (2026-09-29) — what they are, where output goes, fleet, workers, live page
metadata:
  type: project
---

Three new disks in `s3://bim-proprietary-data/` (next to Disk-1/Disk-2), found 2026-09-29. Full living context is in the private
repo `dhigdec/cad-extract-context` (local `/Users/dhiren/Downloads/Deccan/cad-extract-context/CONTEXT.md`) — read it first.

- **Zenitude-data-2** (223 GiB): Smart 3D v13 backup of plant MLNG@1 (SQL Server 2019 .dat, model 167 GB) + ADNOC "Sahil Phase 3"
  P16093 piping drawings (Restricted Circulation; unrelated to the MLNG model). Restored on `cad-zen2-sql` (i-02c20241cf997b48d,
  SQL 2022 Std LI, RHEL). All 1,875 tables exported to JSONL. The model stores plain coordinates (ROUTEPipePort, pipe path features,
  welds, STRUCTMemberPartAxisLin, EQUIPPipeNozzle, CORESpatialIndex) → **3D COMPLETE 2026-09-30 03:50Z**: 45,003 JSON+PCF, 1,927 IFC → 1,927 STEP (OCC-validated) + GLB + OBJ + PNG under `zenitude-data-2/model/`; 549,831 model-stored drawings exported; 2D done. Data-4 new IFC/DB1/SDS2 → STEP conversions run from `zentitude-data-4/_control/conv/`.
  SharedContent contains credentials (SSP3D1.ini, .cci) — never publish.
- **Zentitude-data-4** (7.90 TB, 1,499 archives): all 1,154 Disk-1 archives are in it BYTE-IDENTICAL (proven by checksums 2026-09-30, `_state/audit/src_identity_summary.json`) + 345 new archives (1.75 TB); Disk-1 only kept CAD extensions, so
  Dhiren set the goal (2026-09-29): extract ALL of data-4 fully, deepest nesting, nothing skipped, dedup, live stats.
  Worker `zen2/zx_worker.py` (S3 `cad-disk-extract/zentitude-data-4/_control/`). **COMPLETE + VERIFIED 2026-09-30 00:32Z** (1,499/1,499; 117.6M files; completeness 1,490/1,490; `_state/final_verify.json`); fleet released.
- **Data-4 conversions FINAL 2026-09-30 07:37Z:** IFC 11,099/11,157 → STEP (7.70 TB), DB1 1,994/2,258, SDS/2 133/173, 2,448 native STEP;
  433 marker-gap contents restored (re-audit 0 missing). **All CAD instances terminated 07:44Z**, box state backed up under `_state/box_backup/`,
  publisher stopped (restart command in CONTEXT.md). Open: 193 DB1 no_member_layout (decoder), 8 ifcXML, P16093 .nwd (needs Windows).
- **Zenitude-data-3** (3.86 TiB): superset of Disk-2 + ~510 new archives; not started.
- Output: one folder per disk under `s3://annotationprod/cad-disk-extract/<disk-lowercase>/` (Dhiren: never mix disks).
- Live page: https://dhigdec.github.io/cad-extract-status/sources.html (publisher `zen2/publish_sources.py` on the Mac).

See [[feedback-keep-context-repo-updated]], [[feedback-fleet-worker-lessons]], [[project_cad_packaged_dataset]].
