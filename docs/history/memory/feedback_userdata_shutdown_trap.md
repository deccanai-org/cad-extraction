---
name: feedback-userdata-shutdown-trap
description: "CAD fleet user-data ends with `shutdown -h now` + terminate-on-shutdown — pkill of the worker TERMINATES the instance"
metadata:
  node_type: memory
  type: feedback
  originSessionId: e018bae4-0ec8-4915-b8e9-61ca8ae96814
  modified: 2026-09-24T22:15:48.812Z
---

On 2026-09-24 I pkill'd `db1_worker.py` on 4 Hyderabad r7i/c7i machines to restart them with fixed
code; the user-data script treated worker exit as "done", ran `shutdown -h now`, and
`--instance-initiated-shutdown-behavior terminate` destroyed all four. Same pattern exists in
the IFC fleet user-data (`cad-ifc-step*`).

**Why:** a worker-exit-means-done boot script conflates "crashed/killed" with "finished".

**How to apply:** never pkill a fleet worker whose user-data shuts down on exit. New boot scripts
loop (`while true; re-download worker; run; [ -f DONE ] && break`) and only a DONE marker written by
the worker after verifying zero unfinished jobs may lead to shutdown. To restart workers with new
code under the loop script, pkill is then safe. See [[feedback_s3_bulk_copy_worker_design]].

2026-09-25 corollary: the loop fleet ALSO terminates itself the moment every job has a result — the
first pass hit DONE at 04:20 and all 8 instances terminated 3 min before new code was uploaded. Upload
new code (and set `_control/db1-v2/hold`) BEFORE the last jobs finish, or plan to relaunch.

**2026-10-07 repeat (my mistake):** to "remove" a `( sleep 36000; shutdown -h now ) &` auto-off timer I ran
`pkill -f "sleep 36000"` - killing the sleep lets the subshell continue straight into `shutdown`, which TERMINATED two
benches mid-run (HiCAD 42d + GIORGIA lost, ~40 min). Correct way: kill -9 the timer's PARENT subshell (ps -o ppid of the
sleep) first, then the sleep; or never use sleep-then-shutdown timers on boxes you may want to keep (use `shutdown -h +N`,
cancellable with `shutdown -c`).
