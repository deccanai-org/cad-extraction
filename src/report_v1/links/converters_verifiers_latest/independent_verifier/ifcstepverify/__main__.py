"""ifcstepverify command line.

  python -m ifcstepverify pair   --step X.step --ifc A.ifc [--ifc B.ifc] [--ifc-dir DIR] [--manifest manifest.jsonl --step-relpath model/step/X.step] --out DIR
  python -m ifcstepverify s3     --src s3://bucket/projpkg4/ --out s3://bucket/verify/ [--per-project 1 --projects-recent 30 --seed 20260928] [--plan]
  python -m ifcstepverify report --results results.jsonl --out DIR
"""
import argparse, json, os, sys
from . import config as C


def main():
    ap = argparse.ArgumentParser(prog="ifcstepverify", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="verify one STEP against candidate IFC(s)")
    p.add_argument("--step", required=True); p.add_argument("--ifc", action="append", default=[]); p.add_argument("--ifc-dir", action="append", default=[])
    p.add_argument("--ifc-base", help="folder the manifest relpaths are relative to"); p.add_argument("--manifest"); p.add_argument("--step-relpath")
    p.add_argument("--out", required=True); p.add_argument("--stem")
    p.add_argument("--threads", type=int, default=0); p.add_argument("--cand-workers", type=int, default=C.CANDIDATE_BATCH)
    p.add_argument("--step-geom-max", type=float, default=C.STEP_GEOM_MAX_BYTES); p.add_argument("--ifc-geom-max", type=float, default=C.IFC_GEOM_MAX_BYTES)
    s = sub.add_parser("s3", help="batch over S3 packages (EC2)")
    s.add_argument("--src", required=True); s.add_argument("--out", required=True, help="s3://bucket/prefix/ or a local folder"); s.add_argument("--work", default="/data/isv")
    s.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 4), help="packages in flight")
    s.add_argument("--threads", type=int, default=4, help="IfcOpenShell mesh threads per verification")
    s.add_argument("--cand-workers", type=int, default=C.CANDIDATE_BATCH)
    s.add_argument("--min-free-gb", type=float, default=8.0); s.add_argument("--timeout", type=int, default=6 * 3600)
    s.add_argument("--step-geom-max", type=float, default=C.STEP_GEOM_MAX_BYTES); s.add_argument("--ifc-geom-max", type=float, default=C.IFC_GEOM_MAX_BYTES)
    s.add_argument("--match"); s.add_argument("--project-filter", help="regex on project folder names (limits the S3 listing)"); s.add_argument("--projects-recent", type=int); s.add_argument("--per-project", type=int)
    s.add_argument("--sample", type=int); s.add_argument("--seed", type=int, default=C.SEED); s.add_argument("--max-step-gb", type=float)
    s.add_argument("--retry-errors", action="store_true"); s.add_argument("--refresh-inventory", action="store_true"); s.add_argument("--plan", action="store_true")
    r = sub.add_parser("report", help="summaries from results.jsonl"); r.add_argument("--results", required=True); r.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.cmd == "pair":
        from .verify import verify, write
        man = None
        if a.manifest:
            man = {}
            for l in open(a.manifest, encoding="utf-8"):
                if l.strip():
                    m = json.loads(l); man[m["relpath"]] = {"sha256": m.get("sha256"), "bytes": m.get("bytes")}
        res, run = verify(a.step, a.ifc + a.ifc_dir, ifc_base=a.ifc_base, manifest=man, step_relpath=a.step_relpath,
                          step_geom_max=a.step_geom_max, ifc_geom_max=a.ifc_geom_max, threads=a.threads or None, cand_workers=a.cand_workers)
        stem = a.stem or os.path.splitext(os.path.basename(a.step))[0]
        write(res, run, a.out, stem)
        print(json.dumps({"verdict": res["verdict"], "pipeline_issue": res["pipeline_issue"],
                          "reasons": [f"{x['level']} {x['code']}" + (f" x{x['count']}" if x.get("count") else "") for x in res["reasons"]],
                          "digest": res["result_digest"][:16], "seconds": run["t_total_s"]}))
    elif a.cmd == "s3":
        os.makedirs(a.work, exist_ok=True)
        from .s3batch import run
        run(a)
    else:
        from .report import build
        os.makedirs(a.out, exist_ok=True); print(build(a.results, a.out))


if __name__ == "__main__":
    main()
