# sds2-recall-nc1: SDS2 STEP vs the job's own IFC export and NC1 / DSTV files

These tools check the converter's STEP output against two independent records of the same SDS2 job. Both records were
written by SDS2 itself:

- **IFC exports** of the job, for example `50_Binney_Job.ifc`. The tools measure recall and precision per type.
- **NC1 / DSTV files**: one file per fabricated part, with the part's hole list. The tools measure hole recall and
  precision for each part.

All compute runs on the agent box. The Mac only stages files and reads results.

| file | role |
|---|---|
| `stepidx.py` | Streaming STEP indexer. It never builds a B-rep, so a 1-2 GB STEP fits in a few GB of RAM. For each solid it extracts the label, the placed instances (world 4x4), and a PCA box built from its vertices. For each concave cylindrical face it records radius, axis and seam. The face's own vertices are found by walking the face's references: bounds, loops, edges, vertices. From those it records the face's angular span around the axis and its axial interval. |
| `nc1_holes_check.py` | Parses NC1 BO blocks. 5 fields = hole: face, x, y, d, depth. 8 fields = slot: `l` flag, elongation, width, angle. `d = 0` = punch mark, not a hole. It then matches each NC1 part to a STEP piece by section and length (plates: length and width), tight then loose. Holes are matched one-to-one by position along the part, by position across it (plates only) and by diameter. Each part gets one status: `exact`, `count_equal`, `missing_holes`, `extra_holes`, `no_holes_both` or `no_candidate`. |
| `sds2_ifc_recall.py` | Registers STEP to the IFC. The rotation about Z and the translation are voted from long members with the same section on both sides; when sections don't pair, from extents. The identity is also tried and the better one wins. Pieces are then matched one-to-one: PCA-box centres within 25 mm and extents that agree. Output: recall per IFC class/role, precision per STEP kind, section agreement, and the unmatched groups. |
| `ifc_products.py` | Digests each IFC product: ifcopenshell geometry in world coordinates, converted to mm, giving a PCA box, class, Name (the piece mark), ObjectType (the role) and Description (the section). |
| `inv_scan.py` | Inventory. Lists every SDS2 STEP per job and converter label: root files = v4c, `v5.x/` = v5.x, plus the reused v4c of the 759 reuse jobs. Collects the NC1 rows of all 5,992 data-3 and 1,499 data-4 manifests and resolves keys through data-3 / src / data-4 manifest / data-4 marker. |
| `resolve_d12.py` | Resolves NC1 content that is stored only in the Disk-1/2 extraction. The candidates come from the `sha256.nc1` lists in `_state/results` and `_state/ec2-results`, plus the stored keys with the same sanitized name. A key is used only after its sha256 is verified on download. |
| `pair_jobs.py` | Pairs each SDS2 job with nearby NC1 files and IFC exports. Relations: `inside_job`, `sibling` (same parent folder), `same_project` (single-top-folder archive), `same_name` (IFC). |
| `run_jobs.py` | Batch driver. `--phase prep` builds the ground-truth inventory. Files related only by `same_project` are kept only when the NC1 header order line (SDS2's job name) matches the job folder name (similarity >= 0.75). `--phase nc1,ifc` runs the checks for labels v4c and v5.3, with v5.2 / v5.1 standing in when v5.3 is not out. It caches STEP indexes and IFC digests. |
| `conv_jobs.py` | Converts the missing label (v4c or v5.3) for jobs that have ground truth. It uses the official builds, sha256-checked: v4c `c5b65d27...`, v5.3 `81ca1f95...`. It writes to `agentwork/sds2-recall-nc1/conv/<id>/<label>/`, never to the fleet's `conversions/`. |
| `aggregate.py` | Builds per-job, per-label tables, v4c vs v5.x deltas, totals and the worst parts → `out/report.json`. |

## Single job

```
python nc1_holes_check.py --step X_stage2.step --nc1 <dir|zip of .nc1> [--manifest X_stage2_manifest.json] -o out.json --md out.md
python sds2_ifc_recall.py --step X_stage2.step --ifc job.ifc -o out.json --md out.md
```

## Results (S3, bim)

`cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-recall-nc1/`:

- `inv/`: steps, NC1 rows, keys, pairs, nc1_sel
- `out/nc1/<id>_<label>.json|md`
- `out/ifc/<id>_<label>_<ifc8>.json|md`
- `out/report.json`
- `conv/<id>/<label>/`: STEPs converted by this agent
