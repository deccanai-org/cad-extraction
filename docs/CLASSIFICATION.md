# Classification — classes, corpus, tiers (as implemented)

Two independent axes are computed per distinct model (per distinct source content) by
`src/z3conv/coord/build_index.py` (docstring lines 10-14):

- **class** = conversion fidelity relative to the source: 1 complete, 2 partial / stand-ins / needs, 3 broken.
- **corpus** = content richness of the STEP: A / B / C (and R for SDS/2 reference models).

## 1. Owner's names → code

The owner's instruction (2026-10-01, `docs/history/CONTEXT_live_log.md` "DATA-3 → STEP CONVERSIONS"):
*"classify every STEP into 1 perfectly built / 2 partial (needs more files or info, or stand-ins) / 3 damaged"; corpus
framing **A complete / B flagged stand-ins / C members only**.*

| Owner's term | Code field / value | Meaning |
|---|---|---|
| Class 1 "perfectly built" | `class = 1` | every part exact as stored in the source; verified |
| Class 2 "partial" | `class = 2` | usable STEP but something missing / approximated / not yet verified; each row lists `missing` + `needed_to_fix` |
| Class 3 "damaged / bad" | `class = 3` | no usable STEP, or a proven source reason |
| **Class A** "complete" | `corpus = 'A'` | class 1 **with** connection parts (bolts, plates, …) |
| **Class B** "flagged stand-ins" | `corpus = 'B'` | connection parts present but with stand-ins (each listed with its real type) and/or listed missing pieces — i.e. a class-2 steel model, or a class-1 candidate the verifier demoted |
| **Class C** "members only" | `corpus = 'C'` | no connection pieces in the STEP (`source_connections` records whether the source had them); can be class 1 or 2 |
| (R) | `corpus = 'R'` | SDS/2 reference-model jobs written from stored B-reps (DWF import / ReferenceModel) |
| — | `corpus = None` | class 3, or a non-steel model |

So: **A ⊂ class 1; B ⊂ class 2 (steel, with connections); C cuts across 1 and 2; class 3 has no corpus.**
`finish_class()` (build_index.py ~line 472) sets both:

```
if row['class'] == 3:      corpus = None
elif not steel:            corpus = None
elif not has_conn:         corpus = 'C'
elif row['class'] == 1:    corpus = 'A'
else:                      corpus = 'B'
```
and `verify_merge()` demotes a corpus A row to B when the verifier does not confirm class 1.

## 2. Class rules (build_index.py)

### `finish_class(row, has_conn, src_conn, steel)` — the common rule
- **class 3** if any hard `reasons` (failed conversion, unreadable STEP, source not IFC, encrypted, empty, …), or member
  coverage < `class3_member_coverage_below` (0.5), or, without member coverage, part coverage <
  `class3_all_coverage_below` (0.5).
- **class 2** if any coverage (members / connections / other / all) < 1.0, or any non-tolerated stand-in (incl. parts
  named `[approx: …]` in the STEP), or any `needs`, or any `issues` (e.g. `parts_outside_volume_tolerance`, `render_error`).
- **class 1** otherwise.
- `tolerated_standin_types` (rules.json; e.g. `holes_derived_from_bolts` for SDS/2) do not block class 1.

### Per-pipeline classifiers feeding it
- `classify_ifc(c, res, grade)` (~line 516): reuse / convert / failed paths; `IFC_FAIL` maps converter reasons to class-3
  reasons; `input_not_found` (no stored copy, disk lanes) gets **no class** (the 19 "None" rows on data-4).
- `classify_db1(c, res, grade)` (~line 741), `classify_sds2(c, res, grade)` (~line 1014), `classify_sds2_manifest` (~1818).
- `vol_issues()` (~line 443): parts outside ±5% volume → issue; owner-approved volume rule (10-05): a part within 0.5% of
  its own IfcProduct kernel volume is exact (`source_quantity_mismatch` info).
- `grading_failed()`: reused STEP whose re-grade failed → ungraded, or class 3 `reused_step_missing`.

### `verify_merge(row)` (~line 1277) — independent verification
- Class 1 = grader class 1 **AND** verifier PASS (or WARN whose every cause is `source` / `by_design`), no FAIL.
- Not yet verified → class 2 + `class1_pending_verification` (`class1_candidate`).
- Verifier FAIL / non-source WARN → class 2 + `verifier_disagrees`.
- IFC: the verifier is an audit only (owner, 2026-10-02 20:30Z); the grader decides IFC classes. DB1 (Tekla-export
  truth) and SDS/2 (independent decode + SDS2 IFC / KISS / NC1) verdicts are merged.

### Tolerances
Deterministic 0.1 mm (converter-recorded `sew_max_mm` / `gap_max_mm`); larger gaps = `open_in_source` (class 2,
`source_data_absent`). Never keyed on OCC read-time healing.

### Reason categories (every class 2/3 row)
`converter_feature`, `source_file_missing`, `source_data_absent`, `profile_or_catalog_missing`, `source_damaged`.
Aggregate fix plan: `_state/conv/class2_fix_plan.json`.

## 3. Tiers (packaging)

| Tier | Contains | S3 root | Code |
|---|---|---|---|
| **Tier 1 = perfect tier** | class 1 models (IFC by grader; DB1 / SDS2 verified), one primary package per model | `dataset/packages/3d/` | `pkg.py` / `pkgcore.py`, `PKG_TIER` unset |
| **Partial tier** | class 2 models, each row `partial = {kind, issues, missing[], standins[]}` | `dataset/packages/3d_partial/` | same packager, `PKG_TIER=partial` |
| Class 3 | not packaged; listed in the indexes / reports with reasons | `_state/conv/class_3_broken.jsonl.gz` | — |

### Partial kinds — `pkgcore.partial_kind(row)` (src/z3conv/package/pkgcore.py ~line 144)
- **complete_to_source**: every listed shortfall is the source's own (`category == source_data_absent`) AND every stand-in
  is a faithful copy of source geometry (`FAITHFUL_STANDINS = {v6_L4-surface, v6_open-surface, v6_L3-partial-surface,
  reference_open_surface, brep_open_surface}`).
- **approximated**: anything else (member / joist envelopes, concrete prisms, nominal or guessed bolts, bounding boxes,
  shells closed by healing, missing parts).
- DB1 partials ship only on code v (`PKG_PARTIAL_REQUIRE_CODE`).

## 4. Counts (final, 2026-10-06; source `docs/evidence/class_final.json` = FINISH_DONE.json `class`)

| Disk (distinct models) | Class 1 | Class 2 | Class 3 | No class |
|---|---|---|---|---|
| data-3 (8,619) | 2,509 | 5,743 | 367 | — |
| — IFC | 2,414 | 1,535 | 7 | |
| — DB1 | 0 | 105 | 1 | |
| — SDS/2 | 95 | 4,103 | 359 | |
| data-4 (34,113) | 11,309 | 21,568 | 1,217 | 19 |
| — IFC | 11,161 | 7,356 | 415 | 9 |
| — DB1 | 143 | 13,811 | 776 | 10 |
| — SDS/2 | 5 | 401 | 26 | |
| Disk-2 ⊂ data-3 (6,707) | 1,620 | 4,807 | 280 | |
| data-3-only (1,912) | 889 | 936 | 87 | |
| Disk-1 ⊂ data-4 (22,080) | 4,490 | 16,490 | 1,081 | 19 |
| data-4-only (12,033) | 6,819 | 5,078 | 136 | |

Partial-tier kinds (`docs/evidence/stats_p1.json` `partial_kinds`): data-3 1,035 complete_to_source / 4,708
approximated; data-4 977 / 20,013. By pipeline (`docs/evidence/partial_issues.json`): IFC 1,996 c2s / 6,475 approx; DB1
13,883 approx; SDS/2 16 c2s / 4,363 approx. Issue categories counted once per model: converter_feature 23,092,
profile_or_catalog_missing 13,371, source_data_absent 8,964, source_damaged 88.

Note: SDS/2 counts above are per saved state; per-job primaries are smaller (r1: 82 / 1,886 / 174 for data-3).
35 models are class 1 in 3d/ and class 2 in 3d_partial/ (code-u DB1 duplicates) — on the removal list.
