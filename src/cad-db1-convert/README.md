# cad-db1-convert — Disk-1 / Disk-2 era (09-23 → 09-26)

| Path | What |
|---|---|
| `src/db1dec.py`, `db1old.py`, `db1step.py`, `convert_one.py`, `db1_worker.py` | Tekla DB1 decoder → IFC → STEP and its fleet worker |
| `src/pkg_step.py`, `src/ops_2026-09-25/` | packaging of STEP into `dataset/main/{3d,2d}` (projpkg4), posthoc placement, dedup, endgame tools |
| `src/ssm.py` | `ssm.py REGION INSTANCE SCRIPT [timeout]` helper |
| `ud_*.sh` | user-data for DB1 / IFC / packaging / RE boxes |
| `layouts.json` | approved Tekla engine layouts |
| `report_final/` | Disk-1/2 completion report generators (`build_final.py --final`) |
| `oldconv/`, `lead/` | earlier converter copies and the lead's reference material |
Handoff: docs/history/HANDOFF_CAD_STEP.md, PACKAGING_CONTEXT.md.
