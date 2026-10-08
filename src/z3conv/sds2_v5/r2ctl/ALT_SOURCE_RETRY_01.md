# Alternate-source SDS2 retries (in progress)

At 2026-09-29 02:04 UTC, an archive-index read identified three exact normalized-name alternatives with `main/jsetup`, `main/job_mtrl`, `mem/mem_idx`, and `subm/subm_idx` present:

- `IKEA_JOB`: `Disk-2/Completed_Jobs_Data/SDS_Jobs_7.312/Ben Hur Steel.7z`, root `Ben Hur Steel/IKEA_JOB`
- `SimLearn Nation Center_JOB`: `Disk-2/Completed_Jobs_Data/SDS_Jobs_7.312/MMW.7z`, root `MMW/SimLearn Nation Center/SimLearn Nation Center_JOB`
- `1581_J_ Seq 3 thru 5_091515`: `Disk-2/Completed_Jobs_Data/SDS_Jobs_7.331/ME.7z`, root `ME/White Deer ISD/1581_J_ Seq 3 thru 5_091515`

These are alternatives to selected first-pass jobs that failed due to missing `subm/subm_idx`. Their normal first-pass results remain unchanged. Two other checked alternatives (Bishop HS, 19002-IMS6) also lack `subm_idx`; the Cives alternate was checked and lacks it too.

A disjoint retry using the unchanged v4 converter was started on recorded fleet instance `i-0a9be41d2cdd4ad80` via SSM command `2ddbbe3c-10a2-486e-ae88-f02e874f1c54`. It uses separate `/data/out-alt-source-01` and `/data/work-alt-source-01` paths, and writes to `s3://annotationprod/cad-disk-extract/sds2-step-r2-20260929-01/retries/alternate-source-01/`. Source manifest: `control/alt_source_retry_01.json`, SHA256 `655f77db68a752c286f401dafba941d4645d298369de49700c2f7d5ea540116a`. Runner script: `control/run_alt_source_retry_01.sh`, SHA256 `0c8408c2ac7167d4c43943d82790c9f14eb285571354cd4d2cab1b5157096ff7`. No active v4 shard runner was changed.

As of 2026-09-29 02:20 UTC:

- White Deer ISD: `status=ok`, 24,756/24,756 valid STEP solids after read-back, steel ratio 1.008, zero skipped pieces, and the five reported S3 output objects exist. `qa=warn` because 176 joists are approximate member envelopes. This is a source recovery with a material geometry caveat, not an exact reconstruction of every joist. Final canonical promotion is still pending.
- SimLearn Nation Center: `status=ok`, but 23,622/23,625 valid STEP solids; 3 invalid after read-back. Under the run acceptance rule this remains **incomplete** despite the pipeline's `qa=warn`. The five reported S3 objects exist, but do not promote/count this result until the invalid geometry is resolved or explicitly handled as an exception.
- IKEA: conversion still running at the last check; no result yet.

Audit each result for Stage-2 read-back, QA, correct source archive/root, and all expected S3 output objects before treating it as a recovery. Do not count an alternate as an additional unique model.
