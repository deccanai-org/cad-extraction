# Adversarial review of audit-db1-codes

Verdict: **confirmed, with caveats**. The six builder fixes (P1 to P6) hold up on models the audit did not use. Two things are wrong:

- **The integration plan.** Under the worker's best-of rule, the patched STEP is thrown away on almost every model.
- **Several supporting statements.** Some are wrong, some are circular, and some could not tell the two hole rules apart.

## How I tested

- **Where it ran.** All compute ran on BOX-B (ip-10-0-102-51) under `/work/agentwork/review-audit-db1-codes/r2/`, with at most about 18 processes. On the Mac I only ran SSM, copied small files to and from S3, and ran quick Python on small JSON.
- **The A/B setup.** I compared two kits:
  - `l`: the deployed code-l kit.
  - `lfix`: code l plus the audit's `builder_patch.py`.
  - Both use the same ifc2step6 and step_check from code l.
- **Inputs.** The models' own `.db1` files, the audit's per-bolt dumps (`dec/jfix_audit2` with the geometric rule, `dec/jfixr_audit2` with P4), and the bridge's DSTV NC1 files.
- **Outputs.** `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/review-audit-db1-codes/r2/` (stepcmp, holeloss, p6gap, polyalign, ddcmp, nc1web, bridgecat). Scripts are under `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/review-audit-db1-codes/r2/`.
- **Earlier run.** Some STEP runs come from an earlier run of this same review slug on the box (pipeline2: stp/l and stp/lfix). I re-ran its comparisons myself.

## Claims that held up on different cases

| Claim | Independent result |
|---|---|
| P1: 7.1+ engines store relation records 61 bytes apart, and every cut part has a relation | All 18 models on engines 7.1 and up, patched `db1old`: every cut record has a type-11 relation (7.24: 3,509 of 3,509; 7.30: 8,994 of 8,994). At least 99.6% of type-10 pairs are bolt-to-part. STEP of **b3d488c0a0fd** (7.24, not in the audit's proof set): cuts 0 to 80; the 74 newly cut parts keep 99-99.6% of their volume; 0 invalid, 0 surface-only, 0 missing. cd9207295eb9: cuts 0 to 474, 0 invalid. |
| P5: bent beams placed along the stored polyline | 1,073 of 1,073 bent beams in 9 models: the deployed first-segment part lies inside the bent beam's bounding box (within 2 mm), and every polyline point lies inside it too. |
| P6: removes the surface-only parts caused by near-duplicate holes | 748b957ceace surface-only parts 2 to 0; 9cf26a05e061 2 to 0 (neither is an audit proof model). 1a70f9f2afe4 and c8d753af8630 keep 1 each, caused by a Tekla cut, as the audit said. |
| No invalid solids, no lost parts | 11 lfix STEPs plus 7c68f0c9874e: 0 invalid solids. In 10 A/B models the decoder writes the same number of parts, and 0 written parts are missing from the STEP. |
| P2: catalog crash | 7c68f0c9874e fails to decode under code l. With lfix it gives 3,331 products and 0 invalid. (Code m had already fixed this separately.) |
| P3: 7.30 bolts | Grip agreement 27,599 of 27,716 reproduced from the dumps. The 7.30 STEP (7c82c44be6c7 lfix) was still running when I finished. |
| P4: is Tekla's type-10 relation the bolted-part list? | **Supported, and more strongly than the audit showed.** (1) Grip check, real axial bolts in 82 models: hits restricted to listed parts match the separately decoded grip in 103,809 of 125,329 bolts (82.8%), against 84,611 (67.5%) for all hits. 19,415 bolts get fixed and 217 get broken. (2) Bridge NC1 files on 38bf75653bdc: P4 gives 32 holes on two PL20 5999-long plates (NC1 P/56: 32 holes; the geometric rule gives 64), and 28 holes on two PL15 6005-long plates (NC1 A/102: 28; the geometric rule gives 56). |

## Problems found

1. **Integration: best-of throws the patched output away (major).**
   - What happens: the worker's `est()` ranks runs by (failure, share of parts written, invalid solids, approx_products). P5 adds an honest approx tag to every bent beam, so approx_products always goes up. Cover share and invalid count stay equal.
   - Measured on the A/B models: approx_products in l against lfix:
     - 14e4060080fa 85 / 128
     - 1a70f9f2afe4 53 / 113
     - 4671ea562003 17 / 42
     - 60df895b0327 25 / 70
     - 630488715375 28 / 95
     - 748b957ceace 254 / 362
     - 9cf26a05e061 254 / 362
     - c8d753af8630 98 / 131
     - cd9207295eb9 137 / 759
     - b3d488c0a0fd 0 / 148
   - Result: 10 of 11 patched runs would lose to the earlier STEP. The exception is the bridge, where the code-l STEP was killed (rc -9).
   - Fleet evidence: the deployed code n already contains P1-P6, though it also carries other agents' changes. 26 of its 31 results say "graded worse … earlier STEP kept".
   - Consequence: under the audit's integration step 2 ("Best-of keeps the earlier STEP"), most of the claimed gains never happen. 7.24 parts stay uncut, holes the model does not ask for stay, bent beams stay truncated with no tag, and surface-only parts stay. Integration needs a best-of change, for example excluding the new polybeam approx tag from the count or forcing this re-run through.

2. **P6 merges separate holes that only share an axis line.**
   - The flaw: the audit's "8,766 identical hole pairs" test (`dupholes.py`) checks only the sideways distance between hole axes. The P6 merge has the same test and never checks whether the two holes overlap along the axis.
   - Measured with the P4 hits on 82 models: 7,850 merges. 990 are truly identical, 1,926 overlap but are offset, and **4,934 are two different holes on one line**, separated by more than 50 mm (up to 629 mm, for example W30X132 in 0dd3da934923).
   - What P6 does with them: it cuts one cylinder spanning the whole gap, with no tag.
   - Impact today: none found. All 4,934 are on W shapes, where the gap is air between the flanges. P6 on against off: 6eabb07e7145 has 528 merges and 0 parts change volume by more than 0.1%; 8331439be19a has 376 merges, again 0 changed, and 0 invalid or surface-only parts either way.
   - Fix: still add an axial-overlap condition before using this on other data.

3. **Some of the P4 evidence is circular or does not distinguish the rules.**
   - Head, washer and nut overlaps (15,057 to 6,476 and so on): these count only overlaps with holed plates. Overlaps with any part are unchanged: heads 18,141 against 18,141, nuts 16,324 against 16,324.
   - The 15-mark NC1 check: it gives identical results under l, lfix and lfix with P4 off, so it cannot tell the rules apart.
   - Effects the audit did not report:
     - 990 real bolts and 1,158 holes-only bolts lose every hole (a holes-only group then writes nothing).
     - 2,948 holes are removed from parts that lie inside the decoded grip where no listed plate covers that depth. The 368 on the bridge are the NC1-confirmed plates above, so they are correct. The other 580 are unverified: ba7492de88bd and f2644296e828 (192 each), 0dd3da934923 C7X12.25 (166), 078d01bfe6fe (88), 7c82c44be6c7 (18).
   - Figures that don't come from the final dumps:
     - The summary's "33,886 groups with list; 51,484 / 17,562 / 8,888" come from an earlier dump. In the final dumps, 51,039 of 51,091 groups have a list; the fallback rule for groups without a list runs for only 52 of them; and P4 removes 60,205 of 364,361 holes (82 models).
     - The 7.24 bolt and grip figures cover only 3 of the 16 7.24 models.

4. **`builder_patch.py` is not idempotent.**
   - Second run: the tag `audit P4-P6` is never written into the patched file, so a rerun hits AssertionError and exits with rc=1. The files are not damaged.
   - Partial application: when the db1step anchors fail, as they did on the code-m kit, P1-P3 are already written and P4-P6 are not, which leaves a half-patched kit.
   - Current state: the deployed code-n kit already contains the patches (its `db1old.py` md5 equals the audit's).

5. **P1 side effect.** cd9207295eb9 gains 1 surface-only part (0 to 1) from the newly applied cuts. The audit saw the same kind of thing in 6eabb07e7145.

6. **P5 leftovers.**
   - Bridge runtime: 38bf75653bdc lfix STEP took 4,344 s plus a 587 s check. 75 of 3,150 parts are missing and 6 are surface-only. For comparison, the code-l STEP was killed at 1,058 s.
   - Untagged truncated beams: 19 bent beams in 25 lfix decodes are kept straight because of a frame mismatch. They are still truncated and carry no tag.

## Not fabricated, grader not loosened

- No geometry is invented. Bent-beam paths come from the record's own points, cuts from the record's own relations, and holes are only ever removed. New approximations are tagged (`polybeam`, `coincident bolt holes merged`).
- The grader is not loosened: the approx count goes up.
