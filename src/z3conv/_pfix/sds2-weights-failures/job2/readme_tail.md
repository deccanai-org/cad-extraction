## 6. Regression: the fixer's control jobs (v5.5.3 vs v5.5.3 + this patch)

Inputs: the five control jobs the SDS2 fixer uses (`/work/agentwork/sds2v54/jobs`, used read-only). The baseline is
the fixer's own v553b run (`sds2v54/f553/v553b`). Command: `sds2_to_step.py --stage 2 --verify`.

| control | class | read-back solids (valid) | steel ratio | what changed |
|---|---|---|---|---|
| AGNEWS-R | 2 B -> 2 B | 1,546 (1,546) -> same | 0.9969 -> 0.9969 | nothing (identical counts and stand-ins) |
| GMS | 2 B -> 2 B | 9,171 (9,171) -> same | 1.021 -> 1.021 | nothing |
| AGNEWS-T | 2 B -> 2 B | 5,786 (5,786) -> same | 1.0233 -> 1.0232 | 116 `mesh_cylinder` stand-ins -> the pieces' own closed B-rep: 3 guessed straight rods (pieces exact 1,406 -> 1,522) |
| METHODIST | 2 B -> 2 B | 12,386 (12,386) -> same | 1.007 -> 1.007 | 58 `mesh_cylinder` -> exact B-rep: 10 pieces (4 guessed rods, 6 off-weight rings). Parts written flat after the assembly check: 2 -> 12 |
| TYSONS | 2 B -> 2 B | 6,885 (6,885) -> 6,901 (6,901) | 1.007 -> 1.007 | 146 `mesh_cylinder` -> exact B-rep: 13 guessed rods. The 16 extra read-back solids are multi-lump exact B-reps |

No control lost a solid, a valid solid or a piece. Weight split on the controls:
- `built` (untagged converter primitives): 1.0001-1.0076;
- `exact` (SDS2's B-rep): 0.9965-1.0233.

## 7. What is not fixed here, and why

- **Piece-table layout** (`test` 8.004, Seaport L4 7.619): the piece table is read with the wrong slot layout (names
  `@`, `?`, `TD-`; `test` steel 2,198x). The SDS2 fixer's `slot_size_job` draft (`v5work/decode/piece_table.py`) fixes
  both (section 1e). It is the fixer's code, so it is not duplicated here.
- **5-10x bent-plate / profile fallbacks**: tagged stand-ins, item sds2-approx-pieces-7x. Only the >= 10x / +50 lb
  cases are gated here, because one of them stopped stage 2.
- **Exact solids still invalid after STEP read-back** (POLICE HEADQUARTERS L5x5x5/16: one face of 60 invalid after the
  round trip, and ShapeFix does not repair it): left out and reported as `exact_solid_invalid_at_placement`. A B-rep
  repair (sds2-approx-pieces-7x `brep.py` work) may recover them.
- **Jobs whose folder has no `subm/` at all** (16 of the 21 no-piece-table jobs): members only is all the source
  holds. The job folders are as extracted from their archives (file lists checked in `data/no_table_jobs.json`).
- **SDS2's recorded weight conventions** (section 3b) are source facts, not converter errors: grading rule proposal.
