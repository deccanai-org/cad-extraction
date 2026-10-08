---
name: feedback_s3_bulk_copy_worker_design
description: Design rules for large S3 copy/packaging fleets — learned by breaking each one
metadata:
  type: feedback
---

Four rules, each learned from a failure during the 26M-file CAD packaging run.

1. **A claim-based worker must loop and take over stale claims.** A single-pass
   `pool.map` worker that exits leaves its claim orphaned; every sibling already
   skipped that project as `claimed_elsewhere` and never revisits it, so the work is
   stranded forever. This stalled the run three times and I released claims by hand
   each time before reading the logs. Fix: loop until nothing is unfinished, and treat
   a claim older than ~15 min with no result as abandoned.

2. **Threads vs processes depends on what blocks.** `copy_object` is network wait →
   threads multiply inside a process (16 → 2,736 files/s, 171x). Listing and hashing
   are GIL-bound → use processes (measured 12.7x, matching the packager repo's
   24-threads-91MB/s vs 32-processes-1437MB/s).

3. **Cap concurrency ~128 connections per host.** 640 concurrent TLS connections
   exhausted client socket/TLS resources and produced `SSLError` on ~10k files per
   project — 61,341 silent failed writes. Add a bounded retry: these are client
   resource failures, not bad objects, so the same copy succeeds seconds later.

4. **Monitor error counts, not process liveness.** I watched "are processes running"
   and missed 61k accumulating failures for hours. Also: an in-flight project looks
   defective (missing `model/step`, no `project.json`) because metadata is written
   last — always confirm a project is *complete* before calling it broken.

**Why:** each of these cost hours of wall-clock on a job that was otherwise sound.
**How to apply:** build the loop + stale takeover in from the start, pick the
parallelism model per bottleneck, cap per-host connections, and make the status poll
print failure counts.
