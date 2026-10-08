# STEP conversion

Three source formats are converted to STEP (AP214, one STEP product per part). Code: `src/z3conv/` (Zenitude era) and
`src/cad-db1-convert/` (Disk-1/2 era). Full fix history: `docs/history/CONTEXT_live_log.md` (newest first) and
`docs/history/BUGS.md`; per-converter change logs in `src/z3conv/ifc_v6/CHANGES.md`, `src/z3conv/db1_v2/CHANGES.md`,
`src/z3conv/sds2_v5/CHANGES.md`.

## 1. Pipeline

```
scan (zcensus/zjobs) → jobs per pipeline → convert (fleet, best-of across versions)
   → grade (OCC read-back + part census vs source + render)  ┐
   → verify (independent per-format verifier)                ┴→ build_index.py: class 1/2/3 + corpus → final revision → packaging
```

- **Scan**: `src/z3conv/scan/zcensus.py`, `zjobs.py`, `zjobs2.py` (resolves Disk-1/2 pointer inputs), `zresidual.py`.
  Every distinct content (sha256) is converted once; earlier accepted STEP is reused by sha.
- **Fleet runtime**: `src/z3conv/common/convfleet.py` — host-wide job registry, admission on memory + CPU, systemd scope
  per job (MemoryMax + CPUQuota), measured reservations (1.2 × p95 per size bucket), retries at 1.6 × peak, giant mode,
  per-disk lanes (`CONV_DISK`), hot reload. Workers: `ifc/`, `db1/`, `sds2/`, `grade/`, `final/`, `verify/`
  (each has `run.sh`, `setup.sh`, `userdata.sh`, `worker.py`/`convfleet.py`).
- **Coordinator**: `src/z3conv/coord/coord.sh` → `coord_round.sh` → `build_index.py` every ~2 min (systemd `z3coord` on
  i-039e769ea62de0fa1). Writes `_state/conv/index.jsonl.gz`, `class_{1_complete,2_partial,3_broken}.jsonl.gz`,
  `index_summary.json`, `_state/conv_status.json`.
- **Deploy**: `src/z3conv/deploy.sh <ifc db1 sds2 grade final verify coord package scan>` uploads kits to
  `annotationprod/cad-disk-extract/_control/z3conv/<pipe>/`.

## 2. IFC → STEP (`ifc2step6`)

- Source: `src/z3conv/ifc_v6/ifc2step6.py` (release copies in `ifc/`), on ifcopenshell + OCC.
- Version history: 5.x (Disk-1/2, `ifc2step5.py`) → 6.0.1 (multi-body shell split, real voids, hole-loop rewind,
  seam closing ≤ 0.1 mm, per-part read-back with tagged fallback chain) → 6.1.0 (outer-loop fix, double-sided meshes →
  solids, open shells → tagged surfaces, IfcMappedItem instancing, openings on faceted products) → … → **6.1.10 final**
  (planarity 0.05 mm, pinch split, 900 s fallback budget). 6.1.11-rc2 canary: 317 compared, 24 better, 293 same,
  0 worse — **not promoted** (owner chose Option A).
- Every IFC schema (IFC2X…IFC4X3, ifcZIP, ifcXML; CIS/2 route `cis2step.py`); ifcXML has no reader in ifcopenshell
  (class 3 `ifcxml_reader_unavailable`).
- Failure reasons map: `IFC_FAIL` in `coord/build_index.py`.

## 3. Tekla DB1 → STEP (own decoder)

- Decoder reverse-engineered from Tekla's binary DB1: `db1dec.py` (records), `db1old.py` (6.87/7.01/7.24 engines),
  `db1bolts*.py` (bolt groups: 8.x stride-73 member records, pattern stride-341, attrs stride-317), `db1prof.py`
  (profiles; model's own `profdb.bin` overlay), `fittings.py`, `attrlink.py`, `db1step.py` (→ IFC) then IFC → STEP.
- Code letters (worker constant `CODE`): Disk-1/2 era b…g; Zenitude era j (overlay v2, bolt catalog, washers) → n → p →
  q → r (env Tekla bolt catalog, tagged `tekla_env_catalog`) → **u / v** final (partial tier requires v).
- Engines 6.87–9.50. Known decoder limit: `no_member_layout` on an 8.85/8.07 record variant.
- Disk-1/2 used a Windows box running the original `db1tostep.exe` for 2,905 models plus our decoder for 8,837.

## 4. SDS/2 → STEP (`sds2-step-pipeline`)

- Kit: `src/z3conv/sds2/` (fleet worker) and `src/z3conv/sds2_v5/` (converter dev, regression, releases).
- v4 (Disk-2 run 2) → v5 (derived joists, NaN-frame fix, bent plates, …) → v5.1 (reference models = corpus R,
  `empty_job_proof`) → v5.4 (bolt-derived main-member holes) → … → **v5.5.11 final**. v5.5.12 unbuilt.
- One **primary per job** across saved states (best class → most parts → coverage → latest saved); others tagged
  `older_revision_of`.
- Jobs are packaged as `model/sds2/<job>.zip` (store mode) next to the STEP.

## 5. Grading and verification

- Grader: OCC read-back (STEP < 256 MB; bigger by streamed `step_verify_big`), part census vs source (`grade_join.py`,
  `ifc_census.py`), volume check (±5%, curved band), render.
- Independent verifiers (adapters under `_control/z3conv/verify/`, code `src/z3conv/verify/`): ifc-step-verifier (audit
  only), db1-step-verifier (Tekla's own IFC export as truth), sds2_step_verifier (C1/M1/E1–E3 + SDS2 IFC / KISS / NC1).
  Results `_state/conv/verify/<pipe>/<id>.json`; merge rule in `CLASSIFICATION.md`.

## 6. Final outputs

- `zenitude-data-3/conversions/{ifc-step,db1-step,sds2-step}/`, `zentitude-data-4/conversions/{…}/` (bim bucket).
- Data-4 (first, ungraded pass 09-30): IFC 11,099/11,157 STEP (7.70 TB), DB1 1,994/2,258 (0.84 TB), SDS/2 133/173.
- Final classes: see `CLASSIFICATION.md` §4.
- Data-2 (Smart 3D): 1,927 IFC → 1,927 STEP via `src/zen2/s3d/`; not classified.
