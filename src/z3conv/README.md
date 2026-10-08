# z3conv — conversion fleet, grader/classifier, packager (Zenitude era, 10-01 → 10-08)

| Path | What | Entry points |
|---|---|---|
| `common/` | fleet runtime shared by every pipeline | `convfleet.py` (admission, slots, lanes, giant mode), `grade_join.py`, `ifc_census.py`, `step_check.py`, `userdata.sh`, `run.sh` |
| `ifc/`, `ifc_v6/` | IFC → STEP (`ifc2step6.py`, final 6.1.10); v6 dev, regression, releases, CHANGES.md | `ifc/convfleet.py`, `ifc_v6/ifc2step6.py` |
| `db1/`, `db1_v2/` | Tekla DB1 decoder → IFC → STEP (codes j…v); v2 dev + CHANGES/REGRESSION | `db1/convert_one.py`, `db1/db1dec.py`, `db1/db1step.py` |
| `sds2/`, `sds2_v5/` | SDS/2 fleet worker; converter v5.x dev, kits, regression | `sds2/worker.py`, `sds2/run.sh` |
| `grade/`, `final/`, `verify/` | re-grade reused STEP, final pass, independent verifier adapters | `*/worker.py` / `run.sh` |
| `coord/` | coordinator: index + classifier + verify merge + packaging hook | `coord.sh` → `coord_round.sh` → `build_index.py` (`finish_class`, `classify_ifc/db1/sds2`, `verify_merge`) |
| `package/` | general projpkg4 packager (perfect + partial tier) | `pkg.py` (plan/apply/verify), `pkgcore.py` (`partial_kind`, shipping policy), `adapter_zen3.py`, `adapter_zen4.py`, `worker.py` |
| `scan/` | census + job lists per disk | `zcensus.py`, `zjobs.py`, `zjobs2.py`, `zresidual.py` |
| `tools/z3c_backup/` | coordinator/operator scripts (finisher, packaging loops, verify, report stats) | `finisher.sh`, `pkgperf_loop.sh`, `pkgp_loop.sh`, `pkg_verify_par.sh`, `rep_stats_t5.sh` |
| `tools/ssmcli.sh` | run a script on one box over SSM | `ssmcli.sh <region> <iid> <script> <timeout>` |
| `_audit/`, `_deepdive/`, `_fast/`, `_pfix/`, `_sprint/` | fix-agent workstreams (notes + patches), kept for provenance | — |
| `ref_d4conv/` | data-4 first-pass (09-30) conversion builder code | `conv_status.py` |
| `agentbox/`, `ud/` | user-data for agent boxes and the coordinator | — |
| `deploy.sh`, `launch.sh`, `endgame.sh` | deploy kits to `_control/z3conv/`, launch boxes, endgame | — |

Kits are deployed to `s3://annotationprod/cad-disk-extract/_control/z3conv/<pipe>/`; boxes write state to
`s3://bim-proprietary-data/cad-disk-extract/<disk>/_state/`. See docs/STEP_CONVERSION.md, CLASSIFICATION.md, PACKAGING.md.
