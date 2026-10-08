# cad-extraction

The complete record of Deccan's **CAD data-extraction programme** (Sep–Oct 2026): five source disks of steel-detailing
and plant-design data were fully extracted into S3, deduplicated, every IFC / Tekla DB1 / SDS/2 model was converted to
STEP, graded and independently verified into three classes, and every usable model was packaged in the **projpkg4**
format, in two tiers (perfect and partial). A follow-on phase turns perfect models into parametric build123d scripts
(separate repo: [deccanai-org/parametric-cad](https://github.com/deccanai-org/parametric-cad)).

This repo is meant to be read cold, by a teammate or their Claude, and to be enough to continue the work.

## First hour after cloning

1. Read `docs/CONTEXT.md` (the whole story), then `docs/CLASSIFICATION.md` and `docs/AWS_MAP.md` (section 6 = every location as a clickable link).
2. Get AWS access from the owner: SSO profile `annotationprod-publish` (EC2 / SSM / control writes) and read access to `bim-proprietary-data` (see AWS_MAP section 4). `aws sso login --profile annotationprod-publish --use-device-code`.
3. Browse a perfect-tier package: `aws s3 ls "s3://bim-proprietary-data/cad-disk-extract/dataset/packages/3d/" | head` and one package's `project.json` + `manifest.jsonl` (format in `docs/PACKAGING.md`).
4. To run or extend a pipeline, follow `docs/RUNBOOK.md`; component entry points are in each `src/<component>/README.md`. Fleet rules that cost us hours are in `docs/LESSONS.md` - read them before launching anything.
5. The parametric (build123d) phase lives in https://github.com/deccanai-org/parametric-cad (start with its `docs/CONTEXT.md`).

## Start here

| Read | For |
|---|---|
| [docs/CONTEXT.md](docs/CONTEXT.md) | The whole story: disks, extraction, dedup, conversions, classes, packaging, reports, parametric phase, decisions, open items |
| [docs/NUMBERS.md](docs/NUMBERS.md) | Every final number, each with the file it came from |
| [docs/AWS_MAP.md](docs/AWS_MAP.md) | Where every artifact lives in S3, the fleet, profiles and regions (no secrets) |
| [docs/CLASSIFICATION.md](docs/CLASSIFICATION.md) | Class 1 / 2 / 3, corpus A / B / C, perfect vs partial tier, exactly as the code implements them |
| [docs/STEP_CONVERSION.md](docs/STEP_CONVERSION.md) | The three converters (IFC, Tekla DB1, SDS/2), versions, grading and verification |
| [docs/PACKAGING.md](docs/PACKAGING.md) | projpkg4 format, the general packager, dedup rules, the two tiers |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | How to run / resume / verify things, commands |
| [docs/LESSONS.md](docs/LESSONS.md) | Operating lessons learned the hard way |
| [docs/MILESTONES.md](docs/MILESTONES.md) | Dated timeline |
| [docs/SECRETS_SCAN.md](docs/SECRETS_SCAN.md) | What was excluded / redacted from this repo and how it was scanned |
| `docs/history/` | The original working logs verbatim (live CONTEXT log, HANDOVER, BUGS, PII plan, Disk-1/2 handoffs, memory notes) |
| `docs/evidence/` | The small summary JSONs the headline numbers are cited from |
| `src/` | All code, one folder per component, each with a README naming its entry points |

## Headline numbers (final, 2026-10-06)

| What | Number | Source |
|---|---|---|
| Disks extracted | Disk-1, Disk-2, Zenitude-data-2, Zenitude-data-3, Zentitude-data-4 (sic) | docs/history/CONTEXT_live_log.md §1 |
| Data-3 files extracted (all nesting levels) | 372,225,432 files, 15.23 TB raw, 41.7M unique (5.04 TB) | CONTEXT_live_log.md "DATA-3 FINAL" |
| Data-4 files extracted | 117,573,886 files (18.49 TB), 18,656,435 unique objects stored (4.88 TB) | CONTEXT_live_log.md §5 FINAL |
| Distinct models classified, data-3 | 8,619: class 1 = 2,509 / class 2 = 5,743 / class 3 = 367 | docs/evidence/class_final.json |
| Distinct models classified, data-4 | 34,113: class 1 = 11,309 / class 2 = 21,568 / class 3 = 1,217 / 19 no input | docs/evidence/class_final.json |
| **Perfect tier** (`dataset/packages/3d/`) | **779 projects**, 12,718 distinct class-1 STEP, 15,507,077 distinct files, 5.20 TB; verify 761/779 clean (18 only `step_not_shipped`, awaiting owner removal OK) | docs/evidence/stats_f1.json, FINISH_DONE.json |
| **Partial tier** (`dataset/packages/3d_partial/`) | **2,418 projects** (1,756 partial-only + 662 add-ons), 26,733 class-2 STEP (2,012 complete_to_source / 24,721 approximated), 26.85 TB; verify 2,418/2,418 | docs/evidence/stats_p1.json, FINISH_DONE.json |
| Old Disk-1/2 deliverable (`dataset/main/`) | 2,476 packages (1,286 3d / 1,190 2d), 34,270 STEP, 26.07M files | CONTEXT_live_log.md §3 |
| Parametric phase (separate repo) | 11,832 / 12,735 models processed, 7,835 perfect (2026-10-08 07:37Z) | parametric-cad docs/STATUS.md |

S3 confirmations (read-only listing, 2026-10-08): `dataset/packages/3d/` holds 779 prefixes, `3d_partial/` 2,418,
`dataset/main/3d` 1,286, `dataset/main/2d` 1,190, `dataset/samples/parametric_v1/` 5.

## Repo layout

```
README.md
docs/            narrative + reference docs (see table above)
  history/       original logs and memory notes, verbatim (secret-scanned)
  evidence/      small summary JSONs cited by NUMBERS.md
src/
  zen2/               Zenitude disks: extraction worker (zx_worker.py), move, stats, publishers, data-2 Smart 3D decoder
  z3conv/             conversion fleet: IFC/DB1/SDS2 -> STEP, grader + classifier (coord/build_index.py), packager, tools
  cad-packager/       projpkg4 general packager (original copy + audit/spec + proposed patches)
  cad-db1-convert/    Disk-1/2 era: Tekla DB1 decoder, IFC->STEP, packaging, final report
  report_v1/          per-disk data-pack report generators (perfect + partial)
  partial_modal/      partial-tier parametric completion pipeline on Modal (pmp)
  cad-pii/            PII redaction trial code (planned, not applied)
  cad-extract-status/ public status-site publishers (anonymous numbers)
  cad-extract-context/scripts/  operator scripts used from the Mac
```

No data, extracted files, models, archives or credentials are in this repo (see docs/SECRETS_SCAN.md).
