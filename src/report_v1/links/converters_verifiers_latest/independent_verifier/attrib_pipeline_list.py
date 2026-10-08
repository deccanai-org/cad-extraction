#!/usr/bin/env python3
"""Converter work list from ifc_attrib(_v2) results: models whose problem parts are attributed to the PIPELINE.
  python attrib_pipeline_list.py (--s3-prefix cad-disk-extract/zenitude-data-3/_state/conv/ifc/attrib/ | --dir DIR) --out LIST.jsonl
                                  [--index index.jsonl.gz]
One line per model with pipeline work: {id, surface_pipeline, surface_source, pipeline_by_state, missing_buildable,
missing_other, pipeline_examples [[gid, class, name, state]], missing_examples, class, converter_code, step_key};
totals printed. Reads with the default boto3 credentials (instance role / AWS_PROFILE)."""
import os, sys, json, gzip, glob, argparse, collections

B = "bim-proprietary-data"
SRC = {"faceted_open", "surface_model_open"}


def load_s3(prefix):
    import boto3
    s3 = boto3.client("s3", region_name="ap-south-1"); out = {}
    for p in s3.get_paginator("list_objects_v2").paginate(Bucket=B, Prefix=prefix):
        for o in p.get("Contents", []):
            if o["Key"].endswith(".json"):
                out[o["Key"].rsplit("/", 1)[1][:-5]] = json.loads(s3.get_object(Bucket=B, Key=o["Key"])["Body"].read())
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--s3-prefix"); ap.add_argument("--dir"); ap.add_argument("--out", required=True); ap.add_argument("--index")
    a = ap.parse_args()
    res = load_s3(a.s3_prefix) if a.s3_prefix else {os.path.basename(p)[:-5]: json.load(open(p)) for p in glob.glob(os.path.join(a.dir, "*.json"))}
    idx = {}
    if a.index:
        for l in gzip.open(a.index, "rt"):
            r = json.loads(l)
            if r.get("pipeline") == "ifc": idx[r["id"]] = r
    rows = []; tot = collections.Counter()
    for i, r in sorted(res.items()):
        s = r.get("surface") or {}; m = r.get("missing") or {}
        if r.get("join_mode") == "not_gid" or s.get("n") is None: tot["not_gid"] += 1; continue
        bs = s.get("by_state") or {}
        pb = {k: v for k, v in bs.items() if k not in SRC and not (k in ("surface_model_closed",) and s.get("closed_surface_models") == "source")}
        mc = m.get("by_cause") or {}
        mb = mc.get("buildable", 0) + mc.get("cut_empty", 0) + mc.get("not_buildable", 0)
        tot["models"] += 1; tot["surface_pipeline"] += s.get("pipeline") or 0; tot["surface_source"] += s.get("source") or 0
        tot["missing_pipeline"] += mb; tot["voided"] += mc.get("voided", 0)
        if not (s.get("pipeline") or mb): continue
        x = idx.get(i, {})
        rows.append(dict(id=i, surface_pipeline=s.get("pipeline") or 0, surface_source=s.get("source") or 0, pipeline_by_state=pb,
                         missing_buildable=mc.get("buildable", 0), missing_other={k: v for k, v in mc.items() if k in ("cut_empty", "not_buildable")},
                         pipeline_examples=(s.get("pipeline_parts") or [])[:25], missing_examples=(m.get("examples") or {}),
                         cls=x.get("class"), converter_code=x.get("converter_code"), step_key=x.get("step_key"), attrib_version=r.get("version")))
        tot["models_with_pipeline_work"] += 1
    rows.sort(key=lambda r: -(r["surface_pipeline"] + r["missing_buildable"]))
    with open(a.out, "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    print(json.dumps(dict(tot)))


if __name__ == "__main__":
    main()
