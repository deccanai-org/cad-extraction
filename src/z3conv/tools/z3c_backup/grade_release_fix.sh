#!/bin/bash
# Grade boxes: premature-release check and fix (lead 00:00Z). Cause: grade worker processes idle in the 'hold flag set: waiting' loop
# never took hot reloads, so old generations (from before the verification_complete check, 20:12Z) kept running; at 22:20-22:21Z one of
# them passed its old release check (FINAL_OK + 30 min idle) and wrote released/<host>.json and, most likely, /opt/conv/DONE.grade.
# With DONE.grade present, run.sh exits at its next worker exit and user-data powers the box off (~25 IFC / SDS2 assist jobs on it).
#  1. lists DONE.* / RELEASED.* and moves any DONE.* aside (renamed *.premature.<time>; nothing deleted)
#  2. stops the stale grade worker processes (/opt/conv/kit/grade/worker.py; they hold no grade jobs - the grade queue is empty).
#     run.sh starts a fresh grade worker on the current runtime (which takes hot reloads while idle and checks verification_complete).
#     Assist loops (IFC / SDS2 / verify / package jobs) are separate sessions and are not touched.
#  3. shows the result after 40 s
W=/opt/conv
echo "host $(hostname)"; ls -la $W/DONE.* $W/RELEASED.* 2>/dev/null || echo "no DONE / RELEASED files"
for f in $W/DONE.*; do
  [ -f "$f" ] || continue
  case "$f" in *.premature.*) continue;; esac
  mv "$f" "$f.premature.$(date -u +%H%M%S)" && echo "moved aside: $f"
done
echo "== grade worker processes before (pid, age s)"
ps -eo pid,etimes,args | grep "/opt/conv/kit/grade/worker.py" | grep -v grep | awk '{print $1, $2}'
for p in $(ps -eo pid,args | grep "/opt/conv/kit/grade/worker.py" | grep -v grep | awk '{print $1}'); do kill $p 2>/dev/null && echo "stopped $p"; done
sleep 40
echo "== grade worker processes after"
ps -eo pid,etimes,args | grep "/opt/conv/kit/grade/worker.py" | grep -v grep | awk '{print $1, $2}'
ls -la $W/DONE.* 2>/dev/null | grep -v premature || echo "no active DONE file"
tail -n 3 $W/worker-grade.log | cut -c1-160
uptime
