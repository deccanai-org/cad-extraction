---
name: project-cad-extract-pipeline
description: CAD Disk-1/Disk-2 extraction + DB1→STEP fleet — root causes found 2026-09-23 and the three infrastructure traps that hide them
metadata:
  type: project
---

AWS acct 874846752452, profile `annotationprod-publish`. Fleet: 17 i4i extraction workers
(ap-south-1 + ap-south-2), 1 Windows c7i.24xlarge DB1→STEP converter, status node, medium node.

## 2026-09-23: the 13-hour stall — root cause was NOT what the handoff said
Extraction sealed 0 archives for 13h. Handoff blamed corrupt/encrypted source archives.
Actual cause: **password-protected NESTED zips**. 7-Zip hit an interactive `Enter password`
prompt, got EOF from `stdin=DEVNULL`, aborted the whole parent with `rc=255` ("Break signaled").
Ruled out with evidence: disk (/scratch 3% used), memory (488 GB free, 0 OOM), 7-Zip version
(26.02, current), encoding.
- The handoff's `7z l -slt` test passed because it tested the TOP-LEVEL archive. Failures are
  at `nested:d1`/`d2`. **Always check the `context` field before trusting an archive-level test.**
- Fix: add `-p` (empty password) to the 7z argv. Never let 7-Zip prompt in a headless job.
- Failed-decrypt files land at **0 bytes**, and `process_tree` skips zero-size files, so no
  garbage reaches S3. Verified directly.
- Encrypted zips are skipped and recorded in `encrypted_blocked` (path + member list) per
  Dhiren's instruction: "skip them and make a note those zipped files which cannot be done".
  Scale: ~462 locked zips / 14,316 member files across just 16 archives — mostly submittal
  drawing PDFs under `7. Submittals/OFA & IFF/` and `SF_EPM_Export/`, not 3D models or NC1.

## Three infrastructure traps (each cost real time)
1. **Extraction hot-reload never recycles busy workers.** `maybe_hot_reload_code` early-returns
   once `prev == etag`, so it restarts only workers idle at that single instant. The handoff's
   claim that "busy children recycle after the current attempt" is FALSE. Deploying to the
   control key is NOT enough — force-recycle with `pkill -TERM -f "ec2_worker.py --worker N$"`
   and let the supervisor respawn. Spare long-running heavy shards explicitly.
2. **`os.execv` does not replace the process on Windows.** The DB1 converter's self-update
   called it and silently killed itself. Any deploy to
   `_control/db1-step/db1_step_worker.py` used to kill the converter. Now disabled — updates
   stage to disk and apply on restart. `run.cmd` has NO loop and the task is `/SC ONSTART`,
   so a dead converter stays dead; recovery = `aws ec2 reboot-instances` (SQLite on the gp3
   root persists, `restart_recovery` requeues `working` rows).
3. **DB1 lost-claim path blocked for 10 minutes** (`for _ in range(120): sleep(5)`), then failed
   and retried. With ~400 orphaned claims this deadlocked all 24 workers. Fixed: 30s wait, then
   take over a claim only if >15 min old AND no canonical result; requeue instead of failing.

## SSO policy limits (plan around these)
- `ssm:SendCommand` works **one instance at a time** only — multi-instance is denied.
- `AWS-RunPowerShellScript` is **denied** → the Windows converter is observable only via
  its S3 heartbeat.
- `cloudwatch:GetMetricStatistics` is **denied** → no CPU/network liveness signal.

See [[feedback-verify-against-what-user-sees]] — the same lesson repeated: reproduce the failure
at the exact layer it occurs before believing a diagnosis.
