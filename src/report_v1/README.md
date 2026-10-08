# report_v1 — per-disk data-pack reports

- `build_report.py [RUN]` → `site/` (perfect tier; artifact 3YT7fcZYVGm1AAAiY1AFrR); `build_partial_report.py p1` → `psite/`
  (partial tier; artifact LcKzPRdac52VD2TTUsUQwF); shared `report.css`, `report.js`; `finalize.sh`.
- Inputs `data/*.json` come from coordinator stats runs (`src/z3conv/tools/z3c_backup/rep_stats_*.sh`); only the small
  summary JSONs are kept in `docs/evidence/`. Sample assets (`s3mirror/`, `assets_raw/`) are not in this repo.
