# zen2 — Zenitude disks: extraction, move, stats, publishers, data-2 decoder

| Path | What |
|---|---|
| `zx_worker.py` | the extraction worker (versions a → r): 7-Zip full extraction, nested to depth 15, sha256 dedup (disk-wide + vs earlier disks), S3 claims, hot reload, repair mode |
| `ud_zx_z4.sh`, `ud_zx_z4_hyd.sh`, `ud_zx_z4_canary.sh`, `ud_zx_repair.sh`, `z3/ud_zx_z3.sh` | box user-data for data-4 / data-3 / repair |
| `verify_z4_final.py`, `z4_marker_audit.py`, `src_identity_sha.py`, `z3/z3_audit.py`, `z3/z3_final_counts.py` | completeness / identity / object audits |
| `stats_agg.py`, `publish_sources.py` | live stats aggregator and public status publisher (`sources.html`) |
| `pdf_classify.py`, `pdf_*` | CAD-drawing vs document PDF classification |
| `move/move_worker.py`, `move/ud_move.sh` | annotationprod → bim move (probe/plan/copy/purge/vpurge) |
| `ud_zen2_sql.sh`, `restore_s3d.sh`, `export_db_jsonl.sh`, `export_model_drawings.py` | data-2 Smart 3D restore and exports (SA password read from a root-only file on the box) |
| `s3d/` | own Smart 3D decoder → JSON/PCF/IFC/STEP/GLB/OBJ; `S3D_DATA_MODEL.md` |
| `d2/`, `ud_md_worker.sh`, `ud_s3d3d.sh` | data-2 2D / 3D fan-out workers |
| `ud_conv_ifc.sh`, `ud_conv_db1.sh` | data-4 first-pass conversion boxes |
