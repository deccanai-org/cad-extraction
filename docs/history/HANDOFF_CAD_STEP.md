# Handoff: CAD extraction, STEP conversion and packaging (Disk-1 / Disk-2)

Written 2026-09-29 for continuing this work in the Claude Code CLI (API key, terminal) on this same Mac.
Everything here is current as of the end of the desktop session (work finished 2026-09-26 05:26 UTC).

> **How to start in the terminal**
> ```bash
> cd /Users/dhiren/Downloads/Deccan
> claude            # with ANTHROPIC_API_KEY set in your shell
> ```
> Then tell Claude: "Read HANDOFF_CAD_STEP.md and the memory index before doing anything."
> Launched from `/Users/dhiren/Downloads/Deccan`, the CLI loads the same auto-memory folder
> (`~/.claude/projects/-Users-dhiren-Downloads-Deccan/memory/`), so all lessons and project notes carry over.

---

## 1. Status in one screen

| Area | State |
|---|---|
| Extraction | 3,620 / 3,620 archives done |
| Packaged dataset | `s3://annotationprod/cad-disk-extract/dataset/main/{3d,2d}/` — 2,476 packages (1,286 3d, 1,185 2d, 5 empty), every structure check 0, 0 duplicates |
| STEP in dataset | 34,270 files: 6,220 native, 14,652 from IFC, 13,398 from Tekla DB1 |
| IFC → STEP | 8,764 of 9,129 distinct IFC converted (365 cannot be: 353 grid-only/no geometry, 4 truncated, 3 all-zero, 2 OLE2 docs named .ifc, 2 CIS/2, 1 corrupt) |
| Tekla DB1 → STEP | 8,837 of 9,609 in scope converted, 0 pending; 772 cannot be converted without guessing (reasons in the report) |
| Tekla models with a STEP | 11,742 of 12,514 distinct model DB1 files (2,905 from the original Windows pipeline + 8,837 from our run) |
| Machines | All conversion/packaging EC2 terminated. Only the lead's `cad-disk-extract-hyd-status` (c7i.large) and `cad-disk-extract-hyd-medium` (m7i.4xlarge) run — not ours, never touched |
| Open decision | Old superseded packaging copy at `s3://annotationprod/cad-disk-extract/packaged/` (~18M objects, wrong format). Real dataset is `dataset/main/`. Waiting for Dhiren's OK to delete |

Deliverables:
- Final report (private artifact): https://claude.ai/artifact/KHobBDtMgY9auop34PnBzH — local: `cad-db1-convert/report_final/out/CAD_STEP_Completion_Report.html`
- Live status sheet (GitHub Pages): https://dhigdec.github.io/cad-extract-status/ — repo `git@github.com:dhigdec/cad-extract-status.git`, local clone `/Users/dhiren/Downloads/Deccan/cad-extract-status` (last commit `2a9a13b`)
- For the data owners: Google Doc "Locked and Damaged Files" https://docs.google.com/document/d/13Z-vAA1xTElI-SPR-VmNwn3V6d2WGTPctADczAD96HM/edit , copy-paste page https://claude.ai/artifact/2pciktz1F3VwjdpYTATVZg , Excel `cad-db1-convert/report_final/out/simple/Locked_and_Damaged_Files.xlsx`

---

## 2. Credentials and access (where they live — values are NOT copied here)

All credentials are already configured on this Mac; the terminal Claude uses them in place. Do not paste
secret values into files, chats or commits (see memory `committed-secrets-risk.md`).

| What | Where on this Mac | Notes |
|---|---|---|
| AWS config | `~/.aws/config` | region ap-south-1 default |
| AWS static keys | `~/.aws/credentials` | sections `[bim]` and `[874846752452_S3FullAccess]` |
| SSO cache | `~/.aws/sso/cache/*.json` | refreshed by `aws sso login` |
| SSH key (GitHub) | `~/.ssh/id_ed25519` | used for `git@github.com:dhigdec/*` pushes |
| GCP key | `~/.ssh/google_compute_engine` | gcloud (other projects) |
| GitHub CLI | `gh` (already authenticated) | `gh api repos/dhigdec/cad-extract-status/...` |
| Anthropic | `ANTHROPIC_API_KEY` in your shell env | set it yourself; `ANTHROPIC_BASE_URL` is also set in the desktop env |
| DB credentials (other projects) | memory files `reference_prod_db.md`, `reference_dev_db.md`, `reference_service2_db.md`, `reference_analytics_db.md` | VPN required for 10.x hosts |

AWS account **874846752452**, bucket **annotationprod**, regions **ap-south-1 (Mumbai)** and **ap-south-2 (Hyderabad)**.

### AWS profiles

| Profile | Identity | Can | Cannot |
|---|---|---|---|
| `bim` | IAM user `dhiren@deccan.ai`, static keys | S3 Get/Put/List/CopyObject on `annotationprod` (incl. `cad-disk-extract/*`), read the lead's bucket `bim-census-work-874846752452`, EC2 Describe* | S3 **delete**, SSM, any EC2 change |
| `annotationprod-publish` | SSO role `AWSReservedSSO_annotationprod-s3-access` (sso-session `annotationprod-audit`, start URL `https://identitycenter.amazonaws.com/ssoins-REDACTED`) | S3 incl. **delete** on `cad-disk-extract/*`, `ssm:SendCommand`, Start/Stop/Terminate/Reboot instances, Describe* | New top-level S3 prefixes; `ec2:RunInstances` / `iam:PassRole` per memory `reference_cad_iam_gaps.md` (the fleet was nonetheless launched on 2026-09-25 via `src/launch_fleet.sh` — test with `--dry-run` before relying on it) |
| `annotationprod-audit` | SSO role `S3FullAccess` | S3 | — |

Using SSO from the terminal:
```bash
aws sso login --profile annotationprod-publish           # opens browser; add --use-device-code if headless
aws configure export-credentials --profile annotationprod-publish --format env > /Users/dhiren/Downloads/Deccan/cad-db1-convert/.awsenv
chmod 600 /Users/dhiren/Downloads/Deccan/cad-db1-convert/.awsenv
set -a; . /Users/dhiren/Downloads/Deccan/cad-db1-convert/.awsenv; set +a; unset AWS_PROFILE
```
Role credentials last ~2 h; `export-credentials` refreshes them silently while the SSO session (~8 h after login) is valid.
For read-only monitoring use `export AWS_PROFILE=bim; unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN`.

EC2 instance role on the fleet: `cad-disk-extract-ec2` (S3 read/write/delete on `cad-disk-extract/*`).

---

## 3. S3 layout (`s3://annotationprod/cad-disk-extract/`)

| Prefix | What |
|---|---|
| `Disk-1/`, `Disk-2/` | Extracted archive contents (one folder per archive, flattened name; nested zip members under `<zip>!/`) |
| `dataset/main/3d/<project>/`, `dataset/main/2d/<project>/` | **The deliverable** (projpkg4). Each: `project.json`, `manifest.jsonl`, `model/{step,ifc,db1,db2}/`, `drawings/{pdf,dwg,dxf,dg,dpm}/`, `fab/nc1/`, `tables/{bom,abm,kiss,drawing_index}/`. Flat names, 6-hex suffix on collisions |
| `conversions/db1-step/<sha256>.stp` | Our DB1→STEP outputs |
| `conversions/ifc-step/<etag>_<size>.stp` | IFC→STEP outputs |
| `derived/db1-step/<Disk>/by-sha256/<sha>/` | Original Windows pipeline outputs + `result.json` |
| `_state/db1-v2/{results,claims,hosts,logs,deferred,results_superseded}/` | DB1 worker state |
| `_state/ifc-step/{results,claims,deferred,results_superseded}/` | IFC worker state |
| `_control/db1-v2/` | `db1_jobs.json` (9,609 jobs), `census.jsonl`, `layouts.json` (approved Tekla versions), `pairs.json`, `idle_hook.py`, `src/` (deployed decoder+worker), backups `src_backup_*`, `db1_jobs.before_never_attempted_2026-09-25.json`. **`hold`** flag (absent now) keeps the fleet alive |
| `_control/ifc-step/` | `ifc_jobs.json`, `ifc2step5.py`, `validate_step.py`, `ifc_finish.py`, `rescue/` |
| `_control/packaging/` | `step_v1_ifc`, `step_v1_ifc2`, `step_v1_db1`, `step_v1_db1_posthoc` (179 placements), `step_v1_db1_posthoc2` (865f) plans + `done/`; `endgame/` (markers + box scripts); `verify/` (latest full verify, 16 shards), `verify_endgame/`; `dedup_step/`, `empty_step/` (plans + done records); `refresh/report.json`; `step_v1_db1_posthoc/fix/` (regenerated STEP + scans) and `probe/` |
| `packaged/` | **Old superseded copy — pending delete decision** |

Other buckets: `bim-census-work-874846752452` (lead's projpkg4 work bucket, reachable with `bim`).
Status feed: `https://cad-extract-status-874846752452.s3.ap-south-1.amazonaws.com/status.json`.

---

## 4. Local folders and files on this Mac

| Path | What |
|---|---|
| `/Users/dhiren/Downloads/Deccan/` | Workspace root (launch `claude` here) |
| `cad-db1-convert/` | All CAD/STEP work |
| `cad-db1-convert/src/` | Decoder `db1dec.py`, IFC writer `db1step.py`, `convert_one.py`, worker `db1_worker.py` (+ `.bak_*` history), `pkg_step.py`, `pkg_step_posthoc.py`, `refresh_packaged.py`, `verify_dataset.py`, `ifc_crash_bisect.py`, `ifc_exclude.py`, `ifc_finish.py`, `ifc_concat_fix.py`, `ifc2step5_guard.py`, `compare_pairs.py`, `launch_fleet.sh`, many probes |
| `cad-db1-convert/src/ops_2026-09-25/` | End-of-run tools and data: `pkg_posthoc_run.py` (placement with packaged-identity matching), `dedup_step.py`, `empty_step.py`, `regen_step.py`, `coord_probe.py`, `geom_probe.py`, `ph_*.sh` (box stage scripts), `ifc2step5.py`, `validate_step.py`, `pkg_final.py` (original packager), page/xlsx builders, `orig_db1.json`, `packaged_db1.json`, `db1_never_models.json` |
| `cad-db1-convert/ud_*.sh` | EC2 user-data scripts (fleet, packaging boxes, RE box) |
| `cad-db1-convert/lead-repo/` | Lead's repo (CONTEXT.md, pipeline, docs incl. projpkg4 format) |
| `cad-db1-convert/report_final/` | `build_final.py` (`--final`), `make_extra.py`, `make_report_html.py`, `build_extraction_lists.py`, `ifc_diagnostics.json`, `extra_draft.json`, `raw/` (EC2 extraction failure records + ledger) |
| `cad-db1-convert/report_final/out/` | Report HTML, `summary.json`, `conversions.json` (public, no names), `db1_not_converted.csv`, `ifc_not_converted.csv`, `extraction_*.csv`, `db1_coverage.json` |
| `cad-db1-convert/report_final/out/simple/` | Owner-facing CSVs + `Locked_and_Damaged_Files.xlsx` |
| `cad-db1-convert/.awsenv` | Exported SSO env (temporary, chmod 600, regenerate as above) |
| `/Users/dhiren/Downloads/Deccan/cad-extract-status/` | GitHub Pages repo for the status sheet (`index.html`, `conversions.json`, `status.json`, `publish_loop.sh`) |
| `~/.claude/projects/-Users-dhiren-Downloads-Deccan/memory/` | Auto-memory: `MEMORY.md` index + ~50 notes. CAD ones: `project_db1_step_conversion.md`, `project_cad_packaged_dataset.md`, `project_cad_extract_pipeline.md`, `reference_cad_iam_gaps.md`, `feedback_*` rules |
| `~/Downloads/cad-launch-policy.json` | Draft IAM policy to allow RunInstances/PassRole for the fleet |

---

## 5. What was done, A to Z

1. **Extraction** (earlier sessions): 3,620 archives from Disk-1/Disk-2 into S3. Root cause of a 13 h stall on 2026-09-23 was password-protected *nested* zips making 7-Zip prompt; fix `-p` + skip and record locked zips.
2. **Packaging** into the lead's **projpkg4** format under `dataset/main/{3d,2d}` (3d = holds any STEP). Content dedup inside each project by (channel, ETag, size).
3. **IFC → STEP**: 9,129 distinct IFC via `ifc2step5.py --mode hybrid --prec 2` (ifcopenshell 0.8.4.post1 for finishing runs). Repairs: legacy schema headers, zipped IFC, two exports concatenated in one file, corrupt source coordinates (tessellated), kernel-crash elements found by bisection and excluded (listed per result), a file cut mid-statement.
4. **Tekla DB1 → STEP** (own reverse-engineered decoder, `db1dec.py` + `db1step.py`): scope = every DB1 the original Windows converter reported unsupported/failed (9,568), plus 40 model DB1s nobody had attempted (nested zips / late archives) and 1 left "unknown" = 9,609. Checks before writing: member axis agreement (≥90% per file, parts >15° off dropped), COLUMN parts vertical, plausible profile sizes, AP214 faceted B-rep flavour, OpenCASCADE read-back (<64 MB). Code versions b→g; fixes: cut-frame snapping (near-coplanar boolean hang), arc-point outlines ("arc2"), hang/stall rescue by bisection (865f, two Teton Village H1 versions: 1 element each left out).
5. **Coverage audit** across all archives: 23,294 distinct DB1 in the dataset = 12,513 model DBs + 10,781 `xslib.db1` component libraries (not models; not converted, same as the original pipeline).
6. **Packaging of conversions**: IFC round 1 + 2, DB1 pass, retag (`step_source` native/ifc/db1 on every STEP row), then end-of-run corrections:
   - 123 packaged DB1 copies had a STEP but none placed (source ETag differed between multipart/single-part uploads) → matched by packaged object identity; 179 STEP placed in 138 projects, 82 moved 2d→3d.
   - 168 header-only STEP files (no geometry) written by the original pipeline for its failed runs removed from 43 projects (approved).
   - 31 byte-identical STEP duplicates collapsed in 25 projects, kept row lists `also_converted_from` (approved).
   - 2 DB1 STEP files with a vertex at OpenCASCADE's infinite bound (2e103 mm) regenerated (same parts, clean).
   - Every STEP in the dataset scanned for absurd coordinates (incl. 67 big IFC outputs and 2,905 old-pipeline files): clean. Large extents that remain are real (Texas state-plane coordinates; Teton Village elevation ~1,970 m; one stray real beam in Bend Surgical).
   - 11 IFC + 2 DB1 packaged copies refreshed after repairs; empty probe package `Disk-1___probe` removed (approved).
7. **Final verify**: all 2,476 packages, every check 0, 0 duplicates.
8. **Extraction leftovers for the data owners**: 1,307 password-locked nested zips in 38 archives (41,088 files); 55 nested archives 7-Zip cannot open in 25 archives; 7 damaged (partly extracted). Caveat: these come from the EC2 extraction run (1,113 archives); the earlier baseline run (2,507 archives) logged only 8 bare errors.
9. **Machines**: fleet (13 × r7i.16xlarge), RE box, packaging boxes, old Windows converter — all terminated. Lead's two status boxes untouched.

---

## 6. Common commands

```bash
# read-only look at the dataset
export AWS_PROFILE=bim; unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
aws s3 ls s3://annotationprod/cad-disk-extract/dataset/main/3d/ | head
aws s3 cp s3://annotationprod/cad-disk-extract/dataset/main/3d/<project>/project.json -

# what's running
for r in ap-south-1 ap-south-2; do aws ec2 describe-instances --region $r \
  --filters "Name=tag:Name,Values=cad-*" "Name=instance-state-name,Values=pending,running" \
  --query 'Reservations[].Instances[].[InstanceId,InstanceType,Tags[?Key==`Name`]|[0].Value]' --output text; done

# rebuild the final report and public numbers (read-only on S3)
cd /Users/dhiren/Downloads/Deccan/cad-db1-convert/report_final
AWS_PROFILE=bim python3 build_final.py --final && AWS_PROFILE=bim python3 make_extra.py && python3 make_report_html.py

# update the live status sheet
cp out/conversions.json /Users/dhiren/Downloads/Deccan/cad-extract-status/
cd /Users/dhiren/Downloads/Deccan/cad-extract-status && git add -A && git commit -m "..." && git push

# full structure verify (run in-region on an EC2 box; far too slow from the laptop)
VERIFY_SHARD=i/16 python3 verify_dataset.py      # writes _control/packaging/verify/<i>_of_16.json
```

---

## 7. Rules learned the hard way (also in memory)

- Before terminating "idle" boxes, re-read every host heartbeat (`_state/db1-v2/hosts/*.json` `running`) and `not_done()` over the whole job pool; SIGTERM gives rc -15 which looks final.
- A fleet worker exiting with DONE powers the box off (user-data loop). The `hold` flag keeps them alive; remove it (SSO delete) to release.
- Mumbai CAD fleet ≤ 700 vCPU; overflow to Hyderabad.
- Deleting from the dataset, changing the shared worker, or terminating boxes we didn't launch needs Dhiren's explicit OK.
- Laptop uplink is ~0.3–0.8 MB/s: do heavy S3 work on an in-region box (SSM `AWS-RunShellScript`), not locally.
- Treat IFC/DB1 extents >1e10 mm as broken; very large but finite extents are usually real georeferencing.

---

## 8. Open items

1. Decide on deleting `s3://annotationprod/cad-disk-extract/packaged/` (old wrong-format copy).
2. If the data owners send passwords or fresh copies, re-extract those archives and re-run packaging for the affected projects.
3. Optional: check the 2,507 baseline-era archives for locked nested zips (they were not logged).
