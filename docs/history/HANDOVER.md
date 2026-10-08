# HANDOVER: CAD disks → STEP → 3 classes → packages (read this first)

State as of **2026-10-04 21:15Z (2:15 PM PDT)**. Owner: Dhiren, in California; give times in PDT.
This repo is private (dhigdec/cad-extract-context). It holds the full history:
- `CONTEXT.md`: chronological, newest at the top of section 0;
- `MILESTONES.md`;
- `BUGS.md`: the internal bug log; do not paste it into status replies;
- `PII_PLAN.md`;
- `memory/`: the owner-preference notes, copied from Claude memory.

The public live status site is dhigdec/cad-extract-status (`sources.html`, `graded.html`). It is pushed every 2 min **from AWS** by the
coordinator (systemd `z3status`).

---------------------------------------------------------------------------------------------------------------------------------

## 1. The assignment (owner's words, condensed)

1. Convert every IFC, Tekla DB1 and SDS2 model on every disk to STEP, perfectly, with all fixes and all versions. **Never fabricate
   geometry.**
2. Classify every STEP into exactly 3 classes:
   - **1 perfect**;
   - **2 partial**, listing what is missing and what is needed;
   - **3 bad**.
3. Verify independently (our grader plus an independent verifier, inspired by a teammate's verifier zips in ~/Downloads).
4. Package every class-1 STEP with its archive's files, in **projpkg4** format, automatically. Rules:
   - deduped: one model, ONE package across all disks; no repeated projects;
   - only archives with ≥1 class-1 primary model.
5. Disk order:
   - **data-3 first**, until it is fully packaged;
   - then **data-4**, which contains Disk-1;
   - Disk-2 ⊂ data-3;
   - data-2: census only. Its IFCs are derived from Smart 3D, not customer models.
6. At the end, **one full report per disk**: models, perfect / packaged, partial and bad with reasons, the fixes applied and verified,
   and counts at every stage.
7. Always use every instance fully and intelligently. Work only on deduped content.
8. PII redaction later. It replaces files inside packages in place (plan: `PII_PLAN.md`). Not started.

## 2. AWS layout

- **Account and buckets:** account 874846752452.
  - Data bucket: **bim-proprietary-data** (ap-south-1), prefix `cad-disk-extract/`. Versioning OFF, so deletes are permanent.
  - Control bucket: **annotationprod** (versioning ON), prefix `cad-disk-extract/_control/`.
- **Who can write what:**
  - The Mac's logins **cannot write bim**. `annotationprod-publish` is SSO with an explicit deny; `bim` is a read-only IAM user (it CAN
    write annotationprod `_control`); `cad-operator` is denied.
  - All bim writes are done by the boxes' instance role `cad-disk-extract-ec2`.
  - Control files (kits, env.json, flags) are uploaded from the Mac to annotationprod `_control/z3conv/…`; the boxes read them.
- **SSO:** profile `annotationprod-publish`. It expires after ~8 h. Log in with
  `aws sso login --profile annotationprod-publish --use-device-code --no-browser` and give the owner the URL with `user_code`.
  A deploy.sh fallback to the `bim` profile was denied by the classifier ("Credential Exploration").
- **Regions:** Mumbai ap-south-1 (other teams' ASGs share the ~135 vCPU headroom; don't take it without OK), Hyderabad ap-south-2
  (quota 320), Singapore ap-southeast-1 (quota 256, admin-granted EC2/SSM).
  - The owner was asked to request quota 1,500 in both ap-south-2 and ap-southeast-1:
    `aws service-quotas request-service-quota-increase … --quota-code L-1216C47A`. Check whether it was approved.
- **Fleet:** 28 boxes, 1,728 vCPU.
  - Coordinator: `i-039e769ea62de0fa1` (ap-south-1), running systemd `z3coord` (coord.sh → coord_round.sh → build_index.py, ~2 min
    rounds), `z3status` (status publisher) and one-off units.
  - 4 Singapore i4i.16xlarge: i-02a0e4db441356f49, i-0136ab58ce47f41b1, i-0fed134c0238f96dd, i-0f48db9166230ae6c (sds2 userdata).
  - Box list: `/tmp/z3c/canary_fanout.sh`, which also has region and instance ids.
  - Boxes self-power-off only after FINAL_OK + verification_complete + 30 min idle; never terminate them directly.
- **Commands from the Mac:**
  - run a script on a box: `bash /tmp/z3c/ssmcli.sh <region> <instance> <script> <timeout>`;
  - deploy kits: `bash ~/Downloads/Deccan/z3conv/deploy.sh <ifc db1 sds2 grade final verify coord package scan>`.

## 3. Code (Mac)

- `~/Downloads/Deccan/z3conv/`: the fleet kit.
  - `common/convfleet.py` is the runtime: admission, slots, lanes, giant mode.
  - Pipeline workers: `ifc/ db1/ sds2/ grade/ final/ verify/`.
  - `coord/build_index.py`: grader, classes, verify merge, per-disk rounds, packaging hook.
  - `package/`: the packager, pkg-2026-10-02g plus h:
    - `pkg.py` / `pkgcore.py`;
    - adapters `adapter_zen3.py` and `adapter_zen4.py`;
    - `coord_hook.py`: data-4 runs only when the flag `_control/z3conv/package/active_zen4` exists.
  - `scan/`: zcensus, zjobs, zjobs2, zresidual.
- `~/Downloads/Deccan/zen2/publish_sources.py`: the status publisher. Its env hooks are PUB_PROFILE / PUB_REPO; the copy on the
  coordinator is `/opt/status`.
- `~/Downloads/Deccan/cad-packager/`: the packager's original copy plus `proposed/` patches.
- `/tmp/z3c/`: scratch scripts. NOT durable: scripts named here must be re-created if /tmp was wiped.

## 4. Converters and rules (live)

- **Converters:**
  - IFC **ifc2step6 6.1.10**;
  - Tekla DB1 **code u**;
  - SDS2 **v5.5.11**.
  - **6.1.11-rc2** (`agentjobs/ifcv6/release/`) was canaried on 2026-10-03. The canary LOOPED: the canary-keep rule hides a canary's
    own results, so RERUN_ONCE never saw them as done. It was stopped. The results exist as alternatives, not yet compared.
    **6.1.11 is NOT promoted.**
- **Grader rules** (deployed 10-03 ~08:20Z by the owner's own `deploy.sh coord`):
  - IFC `source_duplicate_globalids` → info;
  - IFC best-of ranks validity before the exact-part count;
  - SDS2 family weight bands per SDS2 convention (owner policy);
  - SDS2 holes derived from bolt records → exact. Guessed bolts stay class 2.
- **Tolerances:** deterministic 0.1 mm (sew / gap); no OCC read-time healing.
- **Admission:** resv_factor 3.0; cpu_frac 0.98 / assist 0.95; recent_s 30; IFC slots 26 / 7; big_max 5; DB1 slots 16.
- **Giant mode:** host ip-172-31-14-199 (ap-south-2), min_exp_gb 150.

## 5. Numbers now (21:06Z, 2026-10-04)

**Data-3** (8,619 distinct models):

| | Class 1 | Class 2 | Class 3 |
|---|---|---|---|
| Total | 2,485 | 5,767 | 367 |
| IFC | ~2,390 | | |
| SDS2 | 95 | | |
| DB1 | 1 | | |

- Packaging: **212 projects, 2,485 class-1 models packaged**, 22 pending jobs, 1 verify failure, removals queue 109.
- Still open: IFC re-runs 236 (looks stuck/looping; investigate), SDS2 1 giant. Verification: 6 without a verdict.

**Data-4** (contains Disk-1). Conversion is **DONE**:

| | Class 1 | Class 2 | Class 3 |
|---|---|---|---|
| IFC (17,479) | 9,000 | 8,068 | 411 |
| DB1 (14,697) | 139 | 13,779 | 779 |
| SDS2 (291) | 2 | 276 | 13 |

- 1,626 models are reused from data-3 by sha; 18 inputs were not found.
- **Packaging: NOT DONE.** The coordinator wrote 519 create jobs (9,141 class-1 models) to `_state/conv/package/jobs_zen4.json`, but
  fleet package workers only read `jobs.json` (data-3), so 0 data-4 packages exist.
- Fix in progress: `/tmp/z3c/pkg_d4_apply.sh` runs those jobs on the coordinator, 16 parallel. Blocked by the expired SSO at handover.
  Alternative: make the package worker read every `jobs_*.json`.
- The data-4 dry run (`/tmp/z3c/pkg_d4_dryrun_quick.sh` → `/opt/pkgdr_q/report.json`) was reviewed:
  - 502 projects, placements = new primary class-1 models;
  - 112 duplicate archives dropped;
  - 1,626 models left to data-3's packages.

**Fleet** was ~15% busy at handover: conversions are done, and packaging hasn't run.

## 6. Open TODO (in order)

1. **Run data-4 packaging** (pkg_d4_apply.sh, or a fleet-worker fix), then verify every package: `pkg.py verify --adapter zen4`, all
   checks 0.
2. **Data-3 finish:**
   - find out why 236 IFC re-runs stay open;
   - run the left-shipped removals: `/tmp/z3c/pkg_left_shipped.sh`. APPLY is owner-approved, after the re-runs drain;
   - final package verify: `/tmp/z3c/pkg_verify_all.sh`;
   - verified final revision.
3. **6.1.11:**
   - compare the canary results (rc vs ctl alternatives);
   - fix the canary loop: canary results must count as "done" for RERUN_ONCE;
   - promote if 0 regressions.
4. **SDS2:**
   - upload the re-open list for ~92 stage-1 rows (fixed QA; ids via the builder's diagnosis);
   - v5.5.12 is unbuilt.
5. **Per-disk final report** (data-3, data-4, Disk-1 ⊂ data-4, Disk-2 ⊂ data-3, data-2 census) from `conv_status.disks` and the
   indexes.
6. **Follow-ups:**
   - 89 truly missing package files (old Disk-1/2 name collisions);
   - the big-file read-back for 324 SDS2 rows (lifts 0);
   - far-coordinate mode (owner decision).
7. **Capacity:** if the quotas are approved, launch more boxes with the same userdata. See CONTEXT.md for the Singapore run-instances
   command.

## 7. Hard rules (owner)

- **No fabricated geometry.** Class 1 = every part exact as stored.
- **No deletes** without the owner's OK. Approved so far:
  - dedup duplicates (done: 28 projects / 243,586 objects / 123.9 GB, plus 66 rows);
  - left-shipped removals after the re-runs drain.
- **Never edit IAM.** Never touch other teams' resources.
- **The permission classifier:** never route a denied action through another agent; ask the owner to approve directly, or have them
  run it with `!`.
- **Secrets:** never print or store keys. The OpenRouter key lives in ~/.config/cad-pii.
- **Agents:** they must not call SendFeedback. Don't paste BUGS.md into replies. Times in PDT.
- **Subagents** (builder, IFC improver, SDS2 fixer) hit the **workspace API usage limit** ("regain access 2026-11-01"). Expect to do
  the work directly.
