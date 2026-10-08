# verify: IFC + DB1 adapters (z3v-2026-10-02a)

Location: `s3://annotationprod/cad-disk-extract/_control/z3conv/verify/`.
The teammate's verifiers ship **unchanged** (`ifcstepverify/` 1.0.0, rules 2026.09.28-1; `db1stepverify/` 1.0.0, rules
2026.09.29-1; their own test suites pass, 18/18 and 22/22). The adapters only feed them local data-3 files, translate our
PRODUCT convention, and map their output into the fleet schema.

Files: `adapter_ifc.py`, `adapter_db1.py`, `z3v_common.py`, `z3v_db1_repro.py` (only with `--repro`), `z3v_scope.py`,
`ifcstepverify/`, `db1stepverify/`, `requirements_ifc_db1.txt`, `files_ifc_db1.json` (sha256 of every file).
Job lists: `ifc/audit_jobs.jsonl` (150 jobs), `db1/jobs.jsonl` (106 jobs), `db1/truth_map.json` (Tekla export candidates).
Grader patches: `patches/`. Test results: `tests/`.

## Environment

The conda env lacks scipy, and both verifiers pin a newer OCC and IfcOpenShell. Use a separate venv:
`python3.12 -m venv /opt/conv/z3v && /opt/conv/z3v/bin/pip install -r requirements_ifc_db1.txt`.
Contents: cadquery-ocp 8.0.1.0.0, ifcopenshell 0.8.5, numpy>=2.3, scipy, pillow, boto3. The OCP wheels need libGL / libGLU /
libXrender / libXext / libSM / libfontconfig / libxkbcommon / libXi even headless (see the verifier's ec2_setup.sh).

## Calls (the worker stages the files and passes local paths)

```
PY=/opt/conv/z3v/bin/python
# IFC (audit): --source = the job's input_key object as stored (zip / gzip / ifc; the adapter unpacks it the way ifc/worker.py does)
$PY adapter_ifc.py --step S.step --source SRC.bin --id <sha256> --out R.json --workdir W [--threads 2]
# DB1: --source = the .db1. The adapter stages this model's Tekla export candidates from bim itself via --truth-map
# (or pass --truth-dir DIR, pre-staged). --record = _state/conv/db1/results/<id>.json (read from bim when omitted)
$PY adapter_db1.py --step S.stp --source IN.db1 --id <sha256> --record REC.json --truth-map db1/truth_map.json --out R.json --workdir W [--threads 2]
```
Exit code is 0 whenever R.json was written, including FAIL, CANNOT_VERIFY and ERROR verdicts.

Files next to R.json, for the worker to upload:
- `R.missing.csv`: every missing or flagged element.
- `R.full.json`: the verifier's own complete result.
- `R.step.png` and `R.vs_tekla.png`: DB1 only.

The worker adds pipeline, step_key, step_etag, verifier_version (the adapter's sha), runtime_s and peak_gb. The adapter also
writes runtime_s and peak_gb itself.

## Output

```
{verdict PASS|WARN|FAIL|CANNOT_VERIFY|ERROR, evidence external_truth|independent_decode|element_match|integrity, tier "n/a",
 findings [{code (verifier's own), level, cause pipeline|source|files|packaging|by_design|decoder|unclassified, cause_orig, count, detail}],
 missing [{what, ids, count, cause}] (<= 200; full list in missing_csv),
 class1_ok, index_missing [{what,count,category}], index_needed_to_fix [{fix,category,key}],   <- ready for build_index
 match / geometry / truth / reproduce summaries, notes, result_digest, versions}
```

**Cause mapping**
- IFC: PIPELINE→pipeline, SOURCE→source, FILES→files, PACKAGING→packaging, BY_DESIGN→by_design, UNCLASSIFIED→unclassified,
  SCOPE→unclassified.
- DB1: PIPELINE→pipeline, DECODER→decoder, SOURCE→source, BY_DESIGN→by_design, EVIDENCE→unclassified. EVIDENCE WARNs
  (stage error, truth timeout) therefore block class 1.
- One documented re-attribution: DB1 `W_PRODUCT_SOLID_COUNT` becomes by_design only when every product whose solid count
  is not 1 is an IfcMechanicalFastener (our bolt-group products carry one solid per bolt, nut and washer). Otherwise it stays
  pipeline.

**Grading rule** (in `z3v_common.class1_gate`; `class1_ok` in the result):
- Class 1 needs verdict PASS, or WARN where every WARN has cause source or by_design, and no FAIL.
- Otherwise the model is class 2. The blocking findings become `index_needed_to_fix` entries with key
  `<category> | verify <pipe> <CODE>`. The category is converter_feature, except source_damaged for cause source and
  source_file_missing for cause files.
- CANNOT_VERIFY and ERROR also block class 1, with the reason `verify <pipe> cannot_verify|error`. Retry these on a bigger
  box before demoting.
- DB1 models without a Tekla export (102 of 106) get evidence `integrity`. Their verdict rests on the record, STEP and
  geometry checks: extent, strays, duplicates, BRepCheck and solid kinds.

**Adapter input translation** (no rule changed):
- Our ifc2step5/6 write `PRODUCT('<GlobalId>','<Name>','<IFC class [v6 tags]>')`. Both verifiers read the first string as the
  name.
- IFC: our GlobalIds go through the verifier's own exact GlobalId mode, so matching is one-to-one. If GlobalId mode cannot
  run, the adapter falls back to the verifier's ifc2step name mode, fed the second string.
- DB1: part names come from the second string, which is the profile.
- Schema fix, mirroring ifc/worker.py fix_schema: IFC2X2_FINAL and similar are declared IFC2X3. This applies to IFC sources
  and to Tekla exports; IfcOpenShell 0.8.5 refuses IFC2X2.

**DB1 stages:**
- record: our data-3 result record. CURRENT_CODE is z3-db1-2026-10-01r, so q results get I_OLDER_CODE (info).
- input, step, geometry and truth: as in the verifier.
- render: kept (PNG output).
- reproduce: off by default (owner, 2026-10-02: it is our own decoder). `--repro` runs code r's convert_one.py exactly as
  db1/worker.py does, with `--decoder-python /opt/conv/ifc84/bin/python` and the kit fetched from `_control/z3conv/db1/`.
- VLM: not run.

## Memory / time (measured on a Mac, 2 threads, nice 19)

| job | STEP | peak RSS | time |
|---|---|---|---|
| IFC 5 models | 1.9-6.9 MB | 0.45-0.57 GB | 7-51 s |
| DB1 7d7b67181db9 | 14.6 MB | 4.3 GB | 20 s |
| DB1 6eabb07e7145 (+2 Tekla exports meshed) | 97 MB | 6.8 GB | 143 s |
| DB1 97c7c25d3237 | 161 MB | 6.4 GB | 239 s |

Gate (need_bytes) suggestions:
- IFC: `max(3 GB, 16 x step_bytes + 10 x ifc_bytes)`. The verifier README gives about 5 GB for a 300 MB STEP and 15-30 GB
  for 1-2 GB.
- DB1: `5 GB + 16 x step_bytes (+ 2 GB with a Tekla export)`. That is about 45 GB for the 2.5 GB STEP (dcdf359ef4a2).
- DB1 `--step-geom-max` defaults to 3e9, so geometry is analysed for every DB1. If a box cannot hold that, the stage is
  skipped (I_GEOMETRY_SKIPPED) and the verdict becomes CANNOT_VERIFY.

## Scope

- DB1: all 106 models (`db1/jobs.jsonl`). 4 have Tekla export candidates: 0f3629014894, 5b33936fcd1e, 6eabb07e7145,
  7a6a190dfd82.
- IFC audit: 100 class 1 + 50 class 2 (`ifc/audit_jobs.jsonl`), stratified by STEP size bucket × converter code (class 1)
  or × first reason (class 2). Regenerate with
  `z3v_scope.py --index index.jsonl.gz --out DIR [--ifc-c1 N --ifc-c2 N]`.
