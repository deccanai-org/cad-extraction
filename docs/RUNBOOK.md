# Runbook

Paths below are repo paths (`src/...`). On the original Mac the same code lives under `~/Downloads/Deccan/<component>/`;
scratch scripts referenced as `/tmp/z3c/*.sh` in the logs are backed up in `src/z3conv/tools/z3c_backup/`.

## 0. Before anything
1. Read `docs/CONTEXT.md` §10 (open items) and the top of `docs/history/CONTEXT_live_log.md`.
2. Login: `aws sso login --profile annotationprod-publish --use-device-code --no-browser` (owner approves the URL).
   Read-only checks: `export AWS_PROFILE=bim`.
3. Rules: no deletes without the owner's explicit OK; never edit IAM; never touch other teams' instances; Mumbai CAD
   vCPU cap; agents write S3 only under their own prefix; never print/store keys; no SendFeedback.

## 1. Inspect state (read-only)
```bash
export AWS_PROFILE=bim; B=s3://bim-proprietary-data/cad-disk-extract
aws s3 cp $B/zenitude-data-3/_state/conv_status.json - | python3 -m json.tool | less    # classes, queues, per-disk blocks
aws s3 ls $B/dataset/packages/3d/ | wc -l          # 779
aws s3 ls $B/dataset/packages/3d_partial/ | wc -l  # 2418
```
Run a script on a box: `bash src/cad-extract-context/scripts/ssmcli.sh <region> <instance-id> <script.sh> <timeout>`
(SSM is one instance per call; start long jobs with `setsid nohup … < /dev/null &`).

## 2. Extraction (a new disk)
- Worker `src/zen2/zx_worker.py` (env ZX_DST / ZX_CTL_BUCKET / ZX_CTL_PREFIX / ZX_PRIOR_LABEL / ZX_PRIOR_INDEX); boot
  scripts `src/zen2/ud_zx_z4.sh`, `src/zen2/z3/ud_zx_z3.sh`. Jobs from the drive report; claims in S3; `hold` flag keeps
  boxes alive; `_control/stop` = minimum worker version.
- Verify: `src/zen2/verify_z4_final.py`, `src/zen2/z3/z3_audit.py`, `src/zen2/z3/z3_final_counts.py`,
  `src/zen2/z4_marker_audit.py`.
- Stats/site: `src/zen2/stats_agg.py` (in-region), `src/zen2/publish_sources.py 120` (publisher).

## 3. Conversions
- Deploy kits: `bash src/z3conv/deploy.sh ifc db1 sds2 grade final verify coord package scan` (owner-run when the
  permission classifier blocks it).
- Launch boxes: `src/z3conv/launch.sh` / per-pipe `userdata.sh` (tag Project=cad; check vCPU quotas first).
- Re-run models: add ids to `_control/z3conv/<pipe>/redo_ids.json` **with `codes`** (an entry without codes loops forever).
- Coordinator: `src/z3conv/coord/coord.sh` (systemd z3coord) → `build_index.py`; `--final` for the final pass.
- New disk: `CONV_DISK=<disk>` lane + `DISK_ROOTS` in build_index.py; scan with `src/z3conv/scan/zcensus.py` / `zjobs.py`.

## 4. Packaging
- Perfect tier loop: `src/z3conv/tools/z3c_backup/pkgperf_loop.sh` (stop: `/opt/pkgperf/stop`).
- Partial tier loop: `src/z3conv/tools/z3c_backup/pkgp_loop.sh` with `PKG_TIER=partial` (stop: `/opt/pkgpartial/stop`).
- Data-4 rounds: `src/cad-extract-context/scripts/pkg_d4_dryrun.sh` → review → `pkg_d4_apply.sh`.
- Verify all: `src/z3conv/tools/z3c_backup/pkg_verify_par.sh` (read-only) or `pkg.py verify --adapter zen3|zen4`.
- Finish: `src/z3conv/tools/z3c_backup/finisher.sh` → `FINISH_DONE.json`.
- Removals (only after owner OK): `src/cad-extract-context/scripts/pkg_left_shipped.sh`, `pkg_dedup_delete.sh`.

## 5. Reports
```bash
# on the coordinator: stats run (≈2.5 min), then copy into report_v1/data/
bash src/z3conv/tools/z3c_backup/rep_stats_t5.sh        # copy with a new RUN default (SSM does not pass env)
python3 src/report_v1/build_report.py f1                 # perfect-tier report -> report_v1/site/
python3 src/report_v1/build_partial_report.py p1         # partial report -> report_v1/psite/ (publish in two parts, >64 MB)
```
Report data JSON (`report_v1/data/`) and sample assets are not in this repo (size / client names); regenerate from S3.

## 6. Parametric
- Perfect tier (pmx): see https://github.com/deccanai-org/parametric-cad (`docs/CONTEXT.md`, `ops/pmx_release.sh`).
- Partial tier (pmp, Modal): `src/partial_modal/docs/README.md`. Scaling requires the owner's cost approval.

## 7. Endgame / shutdown
Boxes self-release after FINAL_OK + verification_complete + idle; before terminating anything, re-read heartbeats and
running jobs; back logs up to `*/_state/box_backup/<box>/`; check for unattached volumes.
