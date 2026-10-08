---
name: project-cad-all-disks-plan
description: Dhiren's assignment (2026-10-03): finish data-3 end to end, then run the same convert/verify/classify/package pipelines on every other disk, then a full per-disk report
metadata:
  type: project
---

Assignment from Dhiren, 2026-10-03 ~02:00Z (in California, times in PDT):
1. **First, finish Zenitude-data-3 completely:**
   - all re-runs with all fixes;
   - grading, independent verification and 3-class classification;
   - packaging of every class-1 STEP: deduped, each model once, one main project per model, no repeated projects;
   - the final package check.
2. **Then, maybe, the other disks** (Disk-1, Disk-2, Zentitude-data-4, Zenitude-data-2). Their STEPs came from older converters and were
   never graded. Run the same pipelines on them: re-convert with the current converters, grade, verify, classify, package with the
   general packager and a per-disk adapter.
3. **At the end, one full report per disk.** For each disk:
   - how many models;
   - how many perfect (class 1) and packaged;
   - partial / bad, with reasons;
   - which fixes were applied and verified;
   - all the stage counts.
- Always use every instance fully and intelligently: Mumbai + Hyderabad + Singapore (ap-southeast-1, quota 256 for now). The Mumbai
  headroom stays reserved for other teams.

**Why:** Dhiren wants one proven pipeline, applied disk by disk, with an auditable result per disk.

**Update 2026-10-03 05:15Z (Dhiren):** don't let the fleet idle. Start the other disks NOW as data-3 drains (data-3 keeps priority):
data-4 first, then Disk-1/2, then data-2. Cross-disk dedup: one model, one package overall (global primary map, sticky to data-3).

**How to apply:** Keep per-disk numbers from the
status / index files so the final report is computed, not estimated. Related: [[project-cad-extract-pipeline]],
[[project-cad-packaged-dataset]], [[feedback-dedup-policy]].
