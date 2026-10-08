---
name: feedback-check-running-jobs-before-terminating
description: "Before terminating \"idle\" fleet boxes, re-read every host heartbeat's running list; I killed 2 in-flight DB1 re-runs by trusting my own job watchlist"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 7c4aa40f-8a98-4322-9286-b3fa20c9602b
  modified: 2026-09-26T00:07:28.647Z
---

Before terminating fleet boxes that look idle, re-read `_state/db1-v2/hosts/<host>.json` for EVERY host (the
`running` list) and re-run `not_done()` over the whole job pool right then. Never rely only on the jobs I happened to be
watching.

**Why:** 2026-09-25 23:49Z I terminated 10 "idle" DB1 boxes after the job I was tracking (865f) finished. Box -58 was
still re-running two Teton Village H1 models (arc-fix rewrites, hung in the STEP stage for 5 h under an older worker
without stall detection). SIGTERM gave rc -15, so the worker recorded step_fail and withdrew the published STEP for one.
The other lost its STEP while its result still said ok. Repair: back up the result to results_superseded/, delete it so
done_now re-runs it, keep one box alive with the hold flag, then refresh the packaged copies.

**How to apply:** also note that rc -15 (SIGTERM) is not in the worker's retry set (-11, 139, 124, 125), so a killed job
looks final. Check `step_rc` before trusting a step_fail. See [[project-db1-step-conversion]], [[feedback-userdata-shutdown-trap]].
