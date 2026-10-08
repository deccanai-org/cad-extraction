# SDS2 → STEP verifier

Run it **after** the conversion pipeline. For every converted file it answers one question: is the conversion correct, is something missing, or is something wrong? It gives the reasons, and a list of exactly what is missing.

It is independent of the converter. It decodes the original SDS2 job itself to work out what *should* be in the STEP, and then checks the STEP against that. Where ground truth exists, it also checks against SDS2's own records and exports:
- recorded weights
- IFC export
- KISS bill of materials
- DSTV NC1 fabrication files

## Run it

```
pip install -r requirements.txt            # numpy scipy cadquery-ocp ifcopenshell py7zr

# one file
python verify/verify.py --job <SDS2 job folder> --step <converted.step> [--gt <project folder with IFC/KISS/NC1>] [--selftest]

# many files (after a conversion batch)
python verify/batch_verify.py jobs.csv summary.csv [--selftest] [--workers N]
#   jobs.csv columns: job, step, gt (optional), ifc (optional)

# before converting (is this job decodable at all?)
python verify/verify.py --job <SDS2 job folder>
```

- **One file:** writes `<step>_verify.md` and `<step>_verify.json`, plus `<step>_verify_missing.csv` when anything is missing.
- **Batch:** writes one row per file in `summary.csv`.

## Verdicts

| verdict | meaning | what to do |
|---|---|---|
| **CORRECT** | every check passed | usable |
| **CORRECT (with warnings)** | nothing failed, but some checks warned (listed in the report) | usable; review the warnings |
| **INCOMPLETE** | the geometry is sound, but items that exist in the SDS2 job are missing from the STEP (check C1). The missing members or pieces are listed in `_missing.csv` | re-convert / fix the converter for those items |
| **INCORRECT** | something in the STEP is wrong: geometry, sections, units, invalid solids, or disagreement with SDS2's own weights / IFC / KISS / NC1 | do not use; the reasons name the failing checks |
| **CANNOT VERIFY** | the SDS2 job's layout could not be decoded, so there is nothing trustworthy to compare against | the job needs decoder support first |
| **READY TO CONVERT / NOT CONVERTIBLE** | pre-conversion gate only (no STEP given) | |

## Corpus tiers (v1.2)

Every verified file also gets a **corpus tier**, which decides which dataset it ships in. The verdict says whether the conversion is right. The tier says what kind of training data the file is. It is written to the report (`## Corpus tier`), the `.json` (`tier`), and `summary.csv` (`tier`, `tier_confidence`, `tier_reasons`, `flag_*`, `flagged_share`, `source_connection_plates`).

| tier | what it is |
|---|---|
| **A** | members + connection pieces (stage 2), no stand-in parts, nothing missing |
| **A-unconfirmed** | as A, but approximate pieces couldn't be told apart (a `--flat` file with no `approx` tags) |
| **B** | stage 2 with flagged stand-in parts, or up to 2% of pieces missing (listed in `_missing.csv`) |
| **C-exact** | members only (stage 1), no stand-in parts |
| **C-flagged** | members only, with flagged stand-ins (in practice: open-web joists written as boxes) |
| **EXCLUDED** | anything else; `tier_reasons` says why |

- **Boxed joists do not exclude a file.** M2 FAIL makes the verdict INCORRECT, but each boxed joist is counted as a `joist_envelope` part and the file goes to B / C-flagged. Any other FAIL excludes the file, and so does C1 FAIL (more than 2% missing). So a file can read `INCORRECT` and `C-flagged` at the same time.
- **`tier_confidence`** is `confirmed` when SDS2's own IFC/KISS/NC1 agrees, or for stage 1 on 7.2xx/7.3xx when SDS2's weights agree. Otherwise it's `pending evidence`. Stage 2 always needs external truth, because its self-test is still weak. Only ship `confirmed` files under their tier.
- **`source_connection_plates`** (stage 1 only) counts connection plates in the SDS2 job. If it's above 0, the job has detailing that this file doesn't carry, so it's a stage-2 candidate. If it's 0, the source is a members-only model. It's empty when the job's piece table can't be read reliably. The reader knows the 7.2xx layout, and on 7.3xx it returns garbage names, so those jobs show "could not tell".
- Gaps every tier shares (no welds, no holes or copes yet) go on the dataset datasheet, not on each file.

**Part tags (converter contract).** The converter tags stand-in parts either in the manifest CSV or inside the solid name. The verifier reads both and counts each tag once.

In the manifest (`<step>_members.csv` / `<step>_pieces.csv`), use a column named after the tag with a true value (`approx` = `1` / `true` / `yes`), or a `flags` / `tags` / `note` column listing tags (`approx;bolt_guessed`). Rows are matched to solids by member id (stage 1), or by member + piece id and `inst` when present (stage 2). The report lists the manifest's columns (`manifest_columns`) and how many solids gained a tag from it (`manifest_tagged_solids`), so you can see what the converter actually wrote.

In the solid name:

```
JOIST 24K4 #12 (joist_envelope)                       stage 1
BEAM #12 / GRATING 1-1/4 (piece 40, grating_envelope)  stage 2
BEAM #12 / L4x4x3/8 (piece 41, inst 2, approx)         stage 2 (existing tag)
... (piece 42, bolt_guessed)                           bolt size guessed, not decoded
```

Without tags, the verifier detects what it can. A joist counts as `joist_envelope` if its solid weighs more than 3× SDS2's recorded weight, or if it is a 6-face box when no weight is recorded. Grating is detected from `GT<n>` / `GRAT` in the section, the member type, or the SDS2 piece-table name. For the production converter, guessed bolts, member envelopes and approximate pieces are read from what it already writes (see *v1.3 changes*), so tags are optional.

## What it checks

| id | check | independent of the converter? |
|---|---|---|
| D1–D6 | the job's layout decodes: version and slot size, shape table against AISC, section field, work points, strays, section index against piece names | yes (reads the SDS2 job) |
| **C1** | **completeness**: every member (stage 1) or placed piece (stage 2) in the SDS2 job is in the STEP; missing and unexpected items listed | **yes** |
| S1–S4 | the STEP parses; solid count matches the manifest; B-reps are valid and closed; names trace back to SDS2 ids; units and extent are right | partly |
| M1–M2 | solid volume × steel density against SDS2's recorded weight, overall and per section family; open-web joists not written as solid blocks | yes |
| G1–G5 | solids on their work lines (length, top of steel, column axis); connectivity; pieces on their parent member; duplicates; each stage-2 piece against a box rebuilt from the job | yes (G5 rebuilds from the job) |
| E1–E3 | SDS2's own IFC export (auto-aligned), KISS bill of materials, NC1 fabrication parts | yes (only when those files exist) |

`--selftest` plants 9 kinds of defect in a copy of the result and confirms that the checks catch them. Any defect it misses is reported as a blind spot.

Every known edge case, and the check that guards it, is listed in `verify/EDGE_CASES.md` (EC-01…EC-51).

## Coverage by SDS2 version

Measured on 70 sample jobs across all 24 versions found on Disk-2; see `samples/calibration.md`. The shape table and member index are self-calibrated per job, so no version is hard-coded.

| versions | layout (auto-detected) | what the verifier can tell you |
|---|---|---|
| 7.2xx, 7.3xx | 510-B BE f64 shapes; 2494 / 2944-B member slots | **Full verdicts.** Decoding proven against SDS2's own IFC (94% of members matched); mass agrees with SDS2 weights to ~1%. |
| 7.0xx, 7.1xx | 178-B BE **f32** shapes; 1280 / 1416-B slots | Full checks run. Decoding has not yet been confirmed against ground truth, so a CORRECT verdict here is backed by internal checks only. Many samples come out INCORRECT on extent (S4 / D4), so treat these results as provisional. |
| 7.4xx, 2015.x, 7.5xx, 7.6xx | 390 / 398 / 406 / 470 / 249-B **LE** shapes; 2976–3600-B slots | The gate calibrates, but sections resolve for only part of the members. Most jobs come out INCORRECT or CANNOT VERIFY: they are not trusted, and not passed silently. |
| empty / placeholder jobs | – | NOT CONVERTIBLE / CANNOT VERIFY, with the reason. |

## Limits (be aware)

- Holes are counted from NC1 but not compared, because the converter does not model holes yet.
- The stage-2 self-test is weaker (30–60% on some defects) while the stage-2 converter still has known defects: a check that already fails cannot fail further.
- Thresholds are calibrated on 70 jobs. Re-check `samples/calibration_thresholds.json` after larger batches.
- Checks against ground truth (E1–E3) apply only when IFC/KISS/NC1 files are supplied (`--gt`); otherwise they are NA, never PASS.

## Files in samples/

- `calibration.md`, `calibration_jobs.csv`, `calibration_thresholds.json`: the 70-job / 24-version mass run on the 16-core VM (`vm/runner.py`, `vm/calib_report.py`). That run used the verifier **before** C1 (independent completeness) and the stricter M1 rules (wrong section and wrong-profile families now FAIL) were added, so its verdict counts are slightly more lenient than v1's.
- `batch_test_summary.csv`, `*_verify.md/.json`, `Binney_stage2_verify_missing.csv`: v1 output on the local test jobs.
- `v1.2_test/`: v1.2 output (with tiers) on Greenwood stage 1 and 50 Binney stages 1 and 2.
- `v1.2.2_test/`: v1.2.2 output, including runs with test manifests carrying `approx` / `flags` columns (`*_tagged.csv`).

`vm/` holds the parallel runner used for mass runs. It takes a manifest of presigned S3 URLs, which is not included (the URLs expire and grant access).

## v1.1 changes (compatibility with the fixed stage-2 converter)

- Piece names may carry `, inst <k>` and other tags such as `, approx`; S3 accepts them.
- Pieces written once but shared by two members (manifest column `also_on_member`) count as present in C1.
- Solids marked `approx` (built from the piece table because the exact geometry could not be read) are counted; more than 5% of solids approximate gives C1 WARN.

## v1.2 changes (corpus tiers)

- New `verify/tiers.py`: corpus tier, tier confidence and per-part flag counts for every file (see *Corpus tiers* above).
- Stage-1 solid names may carry part tags in parentheses, e.g. `JOIST 24K4 #12 (joist_envelope)`; tags are parsed for both stages.
- `summary.csv` gains `tier`, `tier_confidence`, `tier_reasons`, `flagged_share`, `converter_tagged`, `source_connection_plates` and `flag_*` columns.
- Checks and verdicts are unchanged.

## v1.3.2 changes (decisions 2026-10-02)

- **Three confidence levels** (`tier_confidence`):
  - `confirmed (outside evidence)`: SDS2's own IFC / KISS / NC1 agree with the file.
  - `confirmed (internal checks)`: stage 1 on 7.2/7.3 with SDS2's weights agreeing; or stage 2 with every expected piece present (C1 PASS/WARN), every piece's weight agreeing with SDS2's (M1 PASS) and placements rebuilt (G5 PASS/WARN). **Limit:** a part the shared piece decoder never sees can't be caught this way. On Greenwood, ~950 studs were found only by KISS / NC1.
  - `pending evidence`: neither.
- **Duplicate cleanup** (`--dedup-out DIR` on `verify.py` and `batch_verify.py`, code in `verify/dedup.py`). For each tiered file with converter-made exact duplicates (G4), it writes `DIR/<name>.step` without the repeats, plus `DIR/<name>_dedup.csv` listing what was removed. **The original STEP is never changed.** The copy is read back and must hold exactly the original count minus the removed solids, all valid (`dedup_readback_ok` in `summary.csv`).
  - Converter duplicates no longer lower the tier: **ship the de-duplicated copy.** Above 5% of solids the file is still excluded.
  - Which copy is kept is a convention (lowest member id). The geometry is exact, but a kept shared piece may be linked to the other member of its connection.
  - Re-verifying a de-duplicated copy reports the removed copies as "missing" in C1. That's expected; `_dedup.csv` lists them.
  - Test: 4 of the 5 B jobs had duplicates (5–117 each). All 4 copies read back exactly, and a re-check of MORGAN shows G4 PASS (0 converter duplicates).
- **Known limit, v1 files (run r1):** without the `builder` column, approximate pieces come from the standalone-solid rule, which overcounts. On MORGAN it gave 140 where the converter's `builder` says 2, so approximate counts for r1 files are upper bounds. Every r2 (v4) file has the `builder` column.

## v1.3.1 change (decision 2026-10-02)

- **Guessed bolts don't lower the tier.** Nominal heavy-hex bolts (no SDS2 bolt record for that hole stack) are still counted for every file (`flag_bolt_guessed`, and a line in `tier_reasons`) and stay labelled per bolt in the STEP, but no longer count as flagged solids. Before, almost every stage-2 file dropped to B for them alone. On the 7 test jobs the tiers didn't change (each B file also has approximate pieces or converter duplicates). Flagged solids fell, e.g. SEMINOLE from 674 to 26.

## v1.3 changes (production converter output)

v1.0–v1.2.2 were built and calibrated against a simpler copy of the converter. The production converter (`batch/run_batch.py` → `decode/to_step2.py`, the one that runs on EC2) writes differently, and v1.3 reads it:

- **Assemblies.** Exact pieces are written once and placed per instance as assembly components (the default; `--flat` turns it off). The STEP reader now walks assemblies and applies each component's placement. Before, it saw only top-level shapes: 112 of 677 placed parts on `SAN_YSIDRO_JOB_SW`. Per-part properties are computed once per shared part. Tables cached by older versions are re-read automatically.
- **Bolts** (`BOLT A325N 0.75 x 2.5 (grip 1.25)` from SDS2's bolt records, `BOLT 0.75 x 1.5 grip (nominal heavy hex)` guessed) are kept apart from members and pieces. They aren't in the manifest and belong to no SDS2 piece. They're counted for the tier: each nominal bolt is a `bolt_guessed` flag.
- **Member envelopes** (`... (member envelope)`: members with no fabricated pieces, e.g. joists) count as present in C1, are skipped by G5, are weighed as their member in M1/M2, and are flagged `joist_envelope` (joists) or `approx` (others).
- **Approximate pieces.** In assembly files, a piece written as a standalone solid instead of a component was built by a fallback, not from its B-rep, so it's flagged `approx`. Fasteners and concrete, also standalone, are excluded by their manifest `kind`. In `--flat` files this can't be seen, so an otherwise clean stage-2 file is `A-unconfirmed`. Known limit: the converter writes the few exact parts that fail its assembly self-check as standalone solids (6 of 288 parts on SCHUCKERS), and those are flagged `approx` too.
- **Grating** is SDS2's `GT<n>` pieces (bar grating written as a solid panel), not "GRAT".
- **M1** no longer compares concrete (`Conc…`, or anything weighing 3.1–3.45× as steel, which is SDS2's concrete density) or bar grating against steel weights. It reports what it skipped (`not_compared`).

- **Piece decoders.** `decode/piece_table.py` and `decode/instances.py` are now the production converter's versions, which read the 7.1, 7.2/7.3 and 7.4 piece layouts. The old ones read 7.243 only: on Greenwood (7.312) they found 150 expected pieces instead of 2,926, with garbage weights. The old copies are kept in `decode/_superseded_v1.2/`. The member decoder (`sds2job.py`) stays the verifier's own, which is newer than the converter's.
  - **Trade-off:** C1 (completeness) now uses the same piece decoder as the converter. A piece the decoder can't see is invisible to both, so independent evidence for stage 2 comes from E1–E3 (IFC / KISS / NC1) and M1 (SDS2's weights).
- **S2** no longer requires one solid per part for fasteners (manifest `kind` = fastener). SDS2 bolt and stud pieces are a head, nut and washer written as one compound.
- **S3** treats a repeated name as a problem only when the copies also sit in the same place. The production converter names every placement of a piece on a member the same way.
- **G5** counts only pieces it can rebuild (studs have no outline) and grades on placement: share within 3 in (PASS ≥ 95%, WARN ≥ 85%). Exact agreement within 0.1 in is still reported. Exact B-rep pieces with copes are legitimately smaller than their raw vertex box. This was calibrated on one production job only (Greenwood: 72.6% within 0.1 in, 96.7% within 3 in), so re-check it after the first batch.

- **v4 converter output** (run `sds2-step-r2-20260929-01`):
  - bolt labels ending `(inst N)`
  - main-material envelopes labelled `... (piece N, inst K) member envelope`
  - `_pieces.csv` column `builder`, now the authoritative source for approximate pieces: `profile_fallback` / `plate_fallback` → `approx`, `joist_envelope_approx` → `joist_envelope`, `member_envelope` → envelope
  - `_skipped.csv`: missing pieces in C1 and `_missing.csv` carry the converter's own reason (`converter_skip_reasons`)
- **Stage-2 files: member-decoder checks don't decide.** D3–D6 judge the verifier's reading of the member index (work points, section field). Stage-2 geometry comes from piece placements, so for stage-2 files these are reported in the tier reasons, not counted as failures. On 7.0/7.1 the verifier's member work points mis-decode while the pieces are fine (SEMINOLE: C1 1,748/1,749, M1 median 1.0001).
  - D1/D2 FAIL gives CANNOT VERIFY only when no expected pieces can be decoded. Expected pieces come from the job's `mem/<n>` files when the member index can't be read (AGRANCLISSEMENT: 796 pieces).
- **S4 (stage 2)** compares the STEP's 1st–99th-percentile extent with the pieces' decoded placements, not member work points.
- **G4 duplicates are a flag up to 5% of solids** (`DUP_FLAG_MAX` in `tiers.py`). They're exact repeats written by the converter (the same physical piece under two members; the v4 notes list this as open). The file drops to B and the reasons say to drop the repeats. Above 5% the file is excluded. **This is a policy choice:** set `DUP_FLAG_MAX = 0` to exclude any file with converter duplicates.
- **S2** caps valid, closed multi-body pieces (e.g. `HD1/2` headed anchors, two bodies, weight matching SDS2) at WARN.

**Test on 7 real v4 jobs from r2 (7.0, 7.1, 7.2, 7.3, 7.4, 7.7, 8.0)** (`samples/v1.3_v4test/`):

| Result | Jobs |
|---|---|
| B (all pending evidence) | 5 |
| Excluded for real weight problems: `254S` 74 pieces at 16× SDS2's weight; `RB` 116 round bars at 0.31× | 2 |

Piece checks on the 5 B files: completeness within 3 pieces, weights median 1.0001, placement 95–99% within 3 in. Speed: about 90 s per job per worker, including reading the STEP, on a 6-core laptop.

No re-conversion is needed. Every flag is derived from what the converter already writes.

**Open item (Greenwood stage 2).** E2 (KISS) and E3 (NC1) fail at about 50% piece recall. The unmatched parts (about 950 headed studs `HS0.75X…`, `C6x8.2`, `L5x5x1/2`) aren't in this SDS2 job's piece table at all. So the converter didn't drop them: either the KISS/NC1 files come from a different revision of the job, or SDS2 stores them where we don't decode yet. The checks are left as they are. Stage 1 E2 passes on the same job.

## v1.2.2 changes

- Part tags are also read from the converter manifest, so `approx` marked "in the manifest" (as the converter fix spec asked) now counts in C1 and the tier. `batch_verify.py` writes pre-conversion reports next to `summary.csv` (fixed in v1.2.1).
- Grating is also detected from the member type and the SDS2 piece-table name.
- The piece table is used only when its names look like real SDS2 material. v1.2 reported "connection plates" for 7.3xx jobs from a misread table; those now read "could not tell".
- New report fields: `manifest_tagged_solids`, `manifest_columns`.
