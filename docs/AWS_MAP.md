# AWS map (no secrets)

Account 874846752452. Credentials are never in this repo; they live in `~/.aws` on the operator's Mac (profiles below)
and in the EC2 instance role. Prefixes confirmed by read-only `aws s3 ls` (profile `bim`) on 2026-10-08.

## 1. Buckets

| Bucket | Region | Role | Notes |
|---|---|---|---|
| `bim-proprietary-data` | ap-south-1 | **all data**: raw disks + everything we produced under `cad-disk-extract/` | versioning OFF (deletes are permanent), SSE-S3 |
| `annotationprod` | ap-south-1 | **control plane**: `cad-disk-extract/_control/` (kits, job lists, flags, rules) | versioning ON; the original work location until the 09-30 move (data purged after verified copy) |

## 2. Raw source disks — `s3://bim-proprietary-data/`

| Prefix | Content |
|---|---|
| `Disk-1/` | 1,154 archives, 6.12 TB |
| `Disk-2/` | 2,466 archives, 3.25 TB |
| `Zenitude-data-2/` | Smart 3D backup + P16093 drawings, 223 GiB (**SharedContent holds credentials — never copy**) |
| `Zenitude-data-3/` | 774,328 objects, 3.86 TiB |
| `Zentitude-data-4/` (sic) | 53,443 objects, 7.90 TB |
| `packaged_samples/`, `Final_5_samples/` | others' sample sets (not ours) |

## 3. Our outputs — `s3://bim-proprietary-data/cad-disk-extract/`

| Prefix | What |
|---|---|
| `Disk-1/`, `Disk-2/` | Disk-1/2 extracted CAD-type files (one folder per archive, nested `<zip>!/`) |
| `zentitude-data-4/extracted/<flattened archive>/…` | data-4 full extraction (sha-deduped; pointers in manifests) |
| `zentitude-data-4/source/` | raw copy of the data-4 objects (52,780) |
| `zentitude-data-4/recovered/`, `zenitude-data-3/recovered/<sha256>` | files recovered from source archives for packaging (name collisions) |
| `zenitude-data-3/extracted/` | data-3 full extraction (168,010,409 objects, 3.96 TB) |
| `zenitude-data-2/{source,db,json,extracted,dxf,png,model,model_drawings*,dxf_from_*}/` | data-2: source copy, DB exports (JSONL), 3D model outputs (JSON/PCF/IFC/STEP/GLB/OBJ), model-stored drawings |
| `zenitude-data-3/conversions/{ifc-step,db1-step,sds2-step}/` | data-3 STEP (and Disk-2 by inclusion) |
| `zentitude-data-4/conversions/{ifc-step,db1-step,sds2-step}/` | data-4 STEP (and Disk-1), `_not_accepted/`, `_readback_crash/` |
| `conversions/{db1-step,ifc-step}/`, `derived/db1-step/` | Disk-1/2 era STEP (`<sha256>.stp`, `<etag>_<size>.stp`; Windows pipeline outputs) |
| `sds2-step-r1-…/`, `sds2-step-r2-…/`, `sds2-step-r3-v5proto/`, `sds2-step-r4-v5final/`, `sds2-verify-v1.3-…/` | SDS/2 runs (r1/r2 by an earlier Codex session; superseded) |
| **`dataset/main/{3d,2d}/`** | Disk-1/2 projpkg4 deliverable: 1,286 / 1,190 packages |
| **`dataset/packages/3d/<pid>/`** | **perfect tier, 779 projects** (class-1 STEP; parametric `scripts/` added by pmx) |
| **`dataset/packages/3d_partial/<pid>/`** | **partial tier, 2,418 projects** (class-2 STEP; pmp `scripts/`) |
| `dataset/samples/parametric_v1/<pid>/` | 5 parametric sample packages |
| `packaged/` | superseded first packaging attempt (~18M objects), delete awaiting owner |
| `meshwork/`, `zenitude-data-2-restore-20260929/` | others' / superseded experiments |

### State (written by EC2 boxes only)
| Prefix | What |
|---|---|
| `zenitude-data-3/_state/conv/` | data-3 conversion state: `index.jsonl.gz`, `class_*.jsonl.gz`, `index_summary.json`, `{ifc,db1,sds2}/results/`, `grade/`, `verify/`, `final/r1…`, `package/jobs*.json`, `class2_fix_plan.json` |
| `zenitude-data-3/_state/conv_status.json` | live counts (per disk under `disks[...]`) |
| `zentitude-data-4/_state/conv2/` | data-4 disk-lane state; `DISK_COMPLETE.json` |
| `zenitude-data-3/_state/stats/` | `final_verify.json`, `audit_objects.json` (extraction verification) |
| `zentitude-data-4/_state/` | `final_verify.json`, `conv_final.json`, `audit/src_identity_summary.json`, `audit/marker_missing*.json`, `repair_results/` |
| `_state/packaging/`, `_state/packaging_partial/` | packager ledgers, dry runs, `unresolved/`, `pkg-resolver-d4/disk12_sha_map_all.jsonl.gz` |
| `_state/move/` | annotationprod → bim move: `reconcile2.json`, `vpurged/` |
| `_state/dedup-union/union.sqlite` | Disk-1/2 dedup index (~16.36M sha256) |
| `_state/db1-v2/`, `_state/ifc-step/` | Disk-1/2 era worker state |
| `_state/pm_samples/`, `_state/pm_full/` | parametric samples / full run (claims, hb, done, out, logs) |
| `_state/pmp/` | partial-tier Modal pipeline bundles |
| `_state/report/` | report stats runs (`out/stats_<RUN>.json`) |
| `*/_state/box_backup/<box>/` | logs and scratch backed up from boxes before termination |

### Control — `s3://annotationprod/cad-disk-extract/_control/` (written from the Mac)
| Prefix | What |
|---|---|
| `z3conv/{ifc,db1,sds2,grade,final,verify,package,scan,coord}/` | fleet kits, `rules.json`, `redo_ids.json`, flags (e.g. `package/active_zen4`) |
| `z3conv/agentjobs/`, `*/pfix/` | fix-agent staging (agents write only their own prefix) |
| `z3conv/status/` | status publisher code for the coordinator |
| `z3conv/coord_tmp/pm/full/` | pmx control: `control.json`, `jobs_v*.jsonl.gz`, `code_<ver>.tgz` |
| `move/` | move/purge flags (`stop`, `purge_ok.json`), z3 prior index `z3/prior_sha64.bin` |
| `disk12_sha64.bin`, `zx_env.json`, `report_archives.json` | extraction worker control (data-4 era, under `zentitude-data-4/_control/`) |
| `db1-v2/`, `ifc-step/`, `packaging/` | Disk-1/2 era control |

## 4. Identities (names only)

| Profile / role | Use | Limits |
|---|---|---|
| `bim` (IAM user, static keys in ~/.aws) | read bim bucket; write annotationprod `_control` | cannot write/delete bim; no SSM; cannot read object tags (`--copy-props none`) |
| `annotationprod-publish` (SSO permission set `annotationprod-s3-access`) | SSM (one instance per call), EC2 Run/Start/Stop/Terminate + PassRole, annotationprod S3 incl. delete | explicit deny on the bim bucket; expires ~8 h (`aws sso login --use-device-code`) |
| `cad-operator` (SSO `CAD-Disk-Extract-Operator`) | — | denied on bim |
| EC2 role `cad-disk-extract-ec2` | **all bim writes** (boxes) | Deny on raw source folders; RunInstances works only with tag `Project=cad` (see `history/memory/reference_cad_iam_gaps.md`) |

## 5. Regions, quotas, fleet

- ap-south-1 Mumbai: on-demand quota 2,000 shared with other teams' ASGs — CAD capped at ~700 vCPU (raised to ~1,350
  for pmx 10-08 with top-up loop); spot quota 256 separate.
- ap-south-2 Hyderabad: 320 → 1,500 later; ap-southeast-1 Singapore: 256/320 (admin-granted EC2/SSM).
- Security group `sg-04a594766aa42b691` (egress only) for all boxes; never use `sg-088de8e930b87b429` (open).
- Coordinator `i-039e769ea62de0fa1` (ap-south-1): systemd z3coord, z3status, z3finish, z3pkgperf-loop, z3pkgp-loop.
- All boxes tagged `Project=cad-disk-extract`/`cad`, shutdown behaviour = terminate, self-release on DONE / FINAL_OK.

## 6. Copy-paste links (full S3 URIs + AWS console, region ap-south-1)

| What | S3 URI | Console |
|---|---|---|
| Raw Disk-1 archives | `s3://bim-proprietary-data/Disk-1/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=Disk-1/&showversions=false) |
| Raw Disk-2 archives | `s3://bim-proprietary-data/Disk-2/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=Disk-2/&showversions=false) |
| Raw Zenitude-data-2 | `s3://bim-proprietary-data/Zenitude-data-2/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=Zenitude-data-2/&showversions=false) |
| Raw Zenitude-data-3 | `s3://bim-proprietary-data/Zenitude-data-3/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=Zenitude-data-3/&showversions=false) |
| Raw Zentitude-data-4 | `s3://bim-proprietary-data/Zentitude-data-4/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=Zentitude-data-4/&showversions=false) |
| Disk-1 extracted | `s3://bim-proprietary-data/cad-disk-extract/Disk-1/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/Disk-1/&showversions=false) |
| Disk-2 extracted | `s3://bim-proprietary-data/cad-disk-extract/Disk-2/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/Disk-2/&showversions=false) |
| data-2 outputs | `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-2/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/zenitude-data-2/&showversions=false) |
| data-3 extracted | `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/extracted/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/zenitude-data-3/extracted/&showversions=false) |
| data-4 extracted | `s3://bim-proprietary-data/cad-disk-extract/zentitude-data-4/extracted/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/zentitude-data-4/extracted/&showversions=false) |
| data-3 STEP conversions | `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/conversions/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/zenitude-data-3/conversions/&showversions=false) |
| data-4 STEP conversions | `s3://bim-proprietary-data/cad-disk-extract/zentitude-data-4/conversions/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/zentitude-data-4/conversions/&showversions=false) |
| Disk-1/2-era STEP conversions | `s3://bim-proprietary-data/cad-disk-extract/conversions/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/conversions/&showversions=false) |
| PERFECT TIER (class 1) packages | `s3://bim-proprietary-data/cad-disk-extract/dataset/packages/3d/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/dataset/packages/3d/&showversions=false) |
| PARTIAL TIER (class 2) packages | `s3://bim-proprietary-data/cad-disk-extract/dataset/packages/3d_partial/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/dataset/packages/3d_partial/&showversions=false) |
| Disk-1/2 deliverable (3d / 2d) | `s3://bim-proprietary-data/cad-disk-extract/dataset/main/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/dataset/main/&showversions=false) |
| Parametric 5 samples | `s3://bim-proprietary-data/cad-disk-extract/dataset/samples/parametric_v1/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/dataset/samples/parametric_v1/&showversions=false) |
| data-3 conversion state (index, classes) | `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/zenitude-data-3/_state/conv/&showversions=false) |
| data-4 conversion state | `s3://bim-proprietary-data/cad-disk-extract/zentitude-data-4/_state/conv2/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/zentitude-data-4/_state/conv2/&showversions=false) |
| Packaging state | `s3://bim-proprietary-data/cad-disk-extract/_state/packaging/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/_state/packaging/&showversions=false) |
| Partial packaging state | `s3://bim-proprietary-data/cad-disk-extract/_state/packaging_partial/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/_state/packaging_partial/&showversions=false) |
| Parametric full run (outputs, done markers) | `s3://bim-proprietary-data/cad-disk-extract/_state/pm_full/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/_state/pm_full/&showversions=false) |
| Parametric samples state | `s3://bim-proprietary-data/cad-disk-extract/_state/pm_samples/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/_state/pm_samples/&showversions=false) |
| Report stats | `s3://bim-proprietary-data/cad-disk-extract/_state/report/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/bim-proprietary-data?region=ap-south-1&prefix=cad-disk-extract/_state/report/&showversions=false) |
| Fleet control (kits, rules, flags) | `s3://annotationprod/cad-disk-extract/_control/z3conv/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/annotationprod?region=ap-south-1&prefix=cad-disk-extract/_control/z3conv/&showversions=false) |
| Parametric fleet control | `s3://annotationprod/cad-disk-extract/_control/z3conv/coord_tmp/pm/full/` | [console](https://ap-south-1.console.aws.amazon.com/s3/buckets/annotationprod?region=ap-south-1&prefix=cad-disk-extract/_control/z3conv/coord_tmp/pm/full/&showversions=false) |

Other links: data-pack report (perfect tier) and partial report are Claude artifacts listed in `docs/history/memory/project_zenitude_report.md`; live parametric status https://dhigdec.github.io/cad-extract-status/parametric.html; extraction live page https://dhigdec.github.io/cad-extract-status/sources.html; parametric code https://github.com/deccanai-org/parametric-cad; teammates' packager https://github.com/deccanai-org/cad-dataset-packager.
