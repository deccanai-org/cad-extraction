---
name: feedback-fleet-reboot-idle
description: z3conv fleet boxes that reboot (e.g. OOM hard-hang) come back IDLE — user-data runs on first boot only; per-boot hook fixes it
metadata:
  node_type: memory
  type: feedback
  originSessionId: cc2df5a5-2f05-4112-ac6d-adb750ab0b8a
  modified: 2026-10-06T03:04:46.595Z
---

On 2026-10-06 ~01:30Z, 13 of 21 Hyderabad i4i.16xlarge boxes hard-hung and rebooted. The trigger was raising DB1 `slots` 16→40 (big Tekla models need 40–87 GB each, and the watchdog logged "need 65GB avail 48GB").
EC2 user-data runs only on the first boot, so the rebooted boxes sat at load 0 for up to 1.5 h with no workers. DB1 throughput fell to about 820 models/h.

**Why:** the boot script (common/userdata.sh → run.sh) is first-boot-only, and nothing restarts the workers after a reboot.
**How to apply:**
- Keep DB1 slots ≤ ~26 with mem_floor 0.10 on 495 GB boxes.
- After any slot raise, check every box for `load 0 / 0 worker procs` within the hour, not just one sample.
- `/tmp/z3c/box_revive.sh` (via ssmcli on every box) installs the box's own user-data as a cloud-init per-boot script (`/var/lib/cloud/scripts/per-boot/conv-resume.sh`, which stops a stale md array first). If no worker is running, it also restarts the pipeline. The script keeps the self-power-off behaviour.
- In zsh, unquoted `$ids` does not word-split. Use `${=ids}` in loops over instance ids.

Related: [[feedback-fleet-worker-lessons]], [[feedback-userdata-shutdown-trap]]
