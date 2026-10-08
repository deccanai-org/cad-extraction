---
name: feedback-fleet-worker-lessons
description: Hard-won rules for EC2 extraction fleets driven over SSM (2026-09-29) — setsid, GIL, hot reload, UTF-8 keys, s5cmd, macOS shell
metadata:
  type: feedback
---

Rules learned running the Zentitude-data-4 fleet:
- Background jobs started from an SSM RunShellScript die when the command ends unless detached: `setsid nohup … < /dev/null &` + `disown`.
- One Python process is GIL-bound (~1.7 cores on a 32-vCPU box): run several worker processes per box (multiprocessing), each with its own heartbeat key.
- A worker that never exits never picks up fixes: build in hot reload (exit between jobs when the S3 code ETag changes) and a version-aware stop flag; the boot loop restarts on new code.
- Archive member names can be legacy code page bytes (Python surrogate escapes): S3 keys must be UTF-8 — decode cp1252, keep raw bytes hex in the manifest.
- Big single-object pulls: s5cmd (1.4 GB/s) instead of aws cli (~80 MB/s on RHEL).
- `bim` IAM user cannot read object tags → `aws s3 cp` S3→S3 needs `--copy-props none`.
- The Mac shell is zsh: no word-splitting of `$var`, no `timeout`, BSD sed (no `0,/re/`) — use python for text edits.
- `pgrep -f name` inside an SSM script matches the script itself.
- Heartbeat ages: use `calendar.timegm` / `time.time()`, never `time.mktime(time.gmtime())` (DST off-by-one-hour).
- Dedup markers: a "content stored at K" marker written BEFORE the upload finishes, plus a killed worker (hot reload / stop / crash /
  box release) = marker with no object, and every later copy trusts it. On a marker hit, HEAD its target and upload if missing
  (zx_worker 'o' does this). Audit after any fleet run: shas that occur only as pointers → marker → HEAD (data-4: 433 missing / 471k).
- A ThreadPoolExecutor fed hundreds of thousands of boto3 calls at once (map / as_completed over all items) stalled for 30+ min twice;
  chunk the work (5k per chunk) and use several processes, printing progress per chunk.
- Conversion boxes: several ~200 MB IFC jobs at once filled a 400 GB root (STEP output is 10-40x input) → ENOSPC reported as
  convert_error. Gate big jobs on free disk, classify ENOSPC as retryable.

- Self-shutdown timers written as `( sleep N; shutdown -h now ) &`: killing the `sleep` makes the subshell run `shutdown` at once.
  On 2026-10-02 this terminated BOX-C mid-test. To extend a timer, kill the parent subshell (`pkill -f "sleep N; shutdown"` matches
  the `bash -c` form, or find the PPID of the sleep), never the sleep itself. Then start a new `setsid nohup bash -c 'sleep M; shutdown -h now'`.

**Why:** each of these cost real time on 2026-09-29. **How to apply:** bake them into any new fleet worker/launcher before launch.
Related: [[feedback_s3_bulk_copy_worker_design]], [[feedback-userdata-shutdown-trap]], [[feedback_mumbai_vcpu_cap]].
