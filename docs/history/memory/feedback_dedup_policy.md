---
name: feedback-dedup-policy
description: Dhiren's dedup policy for new source disks — never store content an earlier disk already stored; don't delete existing copies
metadata:
  type: feedback
---

Dhiren (2026-09-29): "i want full deduped of everything" and asked why data-4 re-extracted archives already on Disk-1.
Decision after seeing the numbers: new extractions must NOT upload content whose sha256 is already stored by an earlier
disk (Disk-1/Disk-2 index `cad-disk-extract/zentitude-data-4/_control/disk12_sha64.bin`, built from
`_state/dedup-union/union.sqlite`); record a `disk12:sha256:<hash>` pointer instead. He chose to KEEP the ~1.87M objects /
407 GB already stored before the rule existed (asked explicitly; do not delete them unless he asks again).

**Why:** storage should hold each distinct file once across all disks, but deletions are irreversible and he preferred no risk.
**How to apply:** for every new disk (Zenitude-data-3 next), dedup against all earlier disks' content indexes before upload;
explain up front when an archive set duplicates an earlier disk and why re-opening it is still needed (Disk-1 kept only CAD
extensions). Ask before any bulk deletion. See [[project-zenitude-disks]], [[feedback-fleet-worker-lessons]].
