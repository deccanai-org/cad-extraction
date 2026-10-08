# Final numbers (each with its source)

Abbreviations: **LOG** = `docs/history/CONTEXT_live_log.md`; **EV/** = `docs/evidence/`; **MEM/** =
`docs/history/memory/`. Evidence files are copies of `report_v1/data/*.json` (built from S3 `_state` on the coordinator).

## Extraction

| Number | Value | Source |
|---|---|---|
| Disk-1 / Disk-2 archives extracted | 3,620/3,620 (1,154 + 2,466), 0 failed | LOG §3 |
| Disk-1/2 deliverable `dataset/main` | 2,476 packages (1,286 3d / 1,190 2d incl. 5 empty), 26,071,766 files, 20.68 TB, 34,270 STEP (6,220 native / 14,652 IFC / 13,398 DB1) | LOG §3; S3 listing 10-08 (1,286 / 1,190) |
| Disk-1 ⊂ data-4 | 1,154/1,154 archives byte-identical (6.12 TB), 51,799 identical loose files, 0 different | LOG §5 "Source identity" |
| Data-4 archives | 1,499/1,499 (1,438 ok, 61 partial = source damage) | LOG §5 FINAL (`zentitude-data-4/_state/final_verify.json`) |
| Data-4 files | 117,573,886 (18.49 TB); 18,656,435 unique objects stored (4.88 TB); 105,542 nested archives; 161,941 ransomware-encrypted files | LOG §5 FINAL |
| Data-4 marker repair | 433/433 restored; re-audit 471,478 checked, 0 missing | MILESTONES (09-30 05:45) |
| Data-3 jobs | 5,992/5,992 (5,924 ok, 57 partial, 11 failed) | LOG "DATA-3 FINAL" (`zenitude-data-3/_state/stats/final_verify.json`) |
| Data-3 files | 372,225,432 (15.23 TB raw); 41,726,559 unique (5.04 TB); 35,669,904 new vs earlier disks (3.47 TB) | same |
| Data-3 object audit | 168,010,409 objects (3.96 TB), 0 missing, 0 orphans | LOG (`_state/stats/audit_objects.json`) |
| Data-2 | 1,875 DB tables → JSONL; 45,003 pipelines; 1,927 IFC → 1,927 STEP (2,917,779 parts); 549,831 model drawings | LOG §4 |
| annotationprod → bim move | 37,110/37,110 shards verified; purge 153,604,435 keys | LOG (09-30 23:55Z; 10-02 08:10Z) |

## Conversion classes (final, 2026-10-06)

| Number | Value | Source |
|---|---|---|
| data-3 distinct models | 8,619 → 2,509 / 5,743 / 367 | EV/class_final.json |
| data-4 distinct models | 34,113 → 11,309 / 21,568 / 1,217 / 19 none | EV/class_final.json |
| Disk-2 view | 6,707 → 1,620 / 4,807 / 280 | EV/class_final.json |
| Disk-1 view | 22,080 → 4,490 / 16,490 / 1,081 / 19 | EV/class_final.json |
| data-3-only / data-4-only | 1,912 → 889/936/87; 12,033 → 6,819/5,078/136 | EV/class_final.json |
| Conversion queues open at finish | all 0; 1 DB1 model not waited for | EV/FINISH_DONE.json |

## Packaging

| Number | Value | Source |
|---|---|---|
| Perfect projects | 779 (S3 listing: 779) | EV/stats_f1.json `projects` |
| Perfect distinct class-1 STEP | 12,718 | EV/stats_f1.json `distinct.files["model/step"]` |
| Perfect distinct files / bytes | 15,507,077 / 5,197,347,623,937 B (5.20 TB) | EV/stats_f1.json `distinct.total_*` |
| Perfect verify | 761/779 ok; 18 only `step_not_shipped` (38) | EV/FINISH_DONE.json |
| Perfect by disk | data-3 213 (Disk-2 161, data-3-only 52); data-4 566 (Disk-1 356, data-4-only 210) | MEM/project_zenitude_report.md (report v4) |
| Partial projects | 2,418 = 1,756 standalone + 662 add-ons (S3 listing: 2,418) | EV/stats_p1.json |
| Partial STEP | 26,733 (data-3 5,743 + data-4 20,990 rows) | EV/stats_p1.json `step_rows` |
| Partial kinds | complete_to_source 2,012 / approximated 24,721 | EV/stats_p1.json `partial_kinds` |
| Partial files / bytes | 5,462,092 / 26,851,603,393,176 B (26.85 TB) | EV/stats_p1.json |
| Partial verify | 2,418/2,418 | EV/FINISH_DONE.json |
| Partial by pipeline | IFC 8,471 (1,996 c2s), DB1 13,883, SDS/2 4,379 (16 c2s) | EV/partial_issues.json |
| Removals pending owner | see PACKAGING.md §5 | EV/FINISH_DONE.json |

## Parametric (separate repo)

| Number | Value | Source |
|---|---|---|
| Sample phase | 33 models / 42,199 parts; v7 42,176 parts, 28/33 models perfect | MEM/project_parametric_samples.md |
| Full run (pmx) | 12,735 jobs; 11,832 processed, 7,835 perfect (2026-10-08 07:37Z) | parametric-cad `docs/STATUS.md` |
| Partial tier gap | 5 samples analysed; manifests under-report gaps in 5/5 | MEM/project_partial_tier_parametric.md |
