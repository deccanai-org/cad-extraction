#!/usr/bin/env python3
"""Build the verify job lists from the data-3 index (read-only; run where bim is readable).
  python z3v_scope.py --index index.jsonl.gz --out DIR [--ifc-c1 100 --ifc-c2 50 --seed 20261002]
-> DIR/db1_jobs.jsonl (every DB1 model), DIR/ifc_audit_jobs.jsonl (stratified IFC audit sample), DIR/truth_map.json
Each job: {pipeline, id, class, step_key, input_key, record_key, size, step_bytes, stratum[, truth_candidates]}.
Source resolution (as the fleet does it): _state/conv/<pipe>/results/<id>.json input_key -> grade/jobs.json ('<pipe>-<id>')
-> <pipe>/jobs.json / jobs_reconvert.json."""
import os, sys, json, gzip, random, argparse, collections, posixpath, concurrent.futures as cf
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import z3v_common as Z

B = "bim-proprietary-data"; ST = "cad-disk-extract/zenitude-data-3/_state/conv"


def load_jobs(pipe):
    out = {}
    for k in (f"{ST}/{pipe}/jobs.json", f"{ST}/{pipe}/jobs_reconvert.json"):
        for j in Z.get_json_s3(B, k) or []:
            if isinstance(j, dict) and j.get("input_key"): out.setdefault(j["id"], j["input_key"])
    for j in Z.get_json_s3(B, f"{ST}/grade/jobs.json") or []:
        if j.get("pipeline") == pipe and j.get("input_key"): out.setdefault(j["sha256"], j["input_key"])
    return out


def input_key(pipe, i, jobs):
    r = Z.get_json_s3(B, f"{ST}/{pipe}/results/{i}.json")
    return ((r or {}).get("input_key") or jobs.get(i)), (f"{ST}/{pipe}/results/{i}.json" if r else None)


def truth_map(rows):
    """Tekla export candidates of every DB1 model: IFC models of the index whose archive path sits in the .db1's folder, its
    IFC/ ifc/ Output/ subfolder or its parent (the db1-step-verifier sibling rule), over every archive path of the model"""
    byd = collections.defaultdict(list)
    for r in rows:
        if r["pipeline"] != "ifc": continue
        for p in r.get("paths") or []:
            a, _, m = p.partition(" :: "); byd[(a, posixpath.dirname(m))].append((r["id"], p, r.get("size")))
    out = {}
    for r in rows:
        if r["pipeline"] != "db1": continue
        hits = {}
        for p in r.get("paths") or []:
            a, _, m = p.partition(" :: "); f = posixpath.dirname(m)
            for d, scope in ((f, "same_folder"), (f + "/IFC", "IFC/"), (f + "/ifc", "ifc/"), (f + "/Output", "Output/"), (posixpath.dirname(f), "parent")):
                for iid, ip, sz in byd.get((a, d), []): hits.setdefault(iid, dict(ifc_id=iid, path=ip, size=sz, scope=scope, db1_path=p))
        if hits: out[r["id"]] = list(hits.values())
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--index", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--ifc-c1", type=int, default=100); ap.add_argument("--ifc-c2", type=int, default=50); ap.add_argument("--seed", type=int, default=20261002)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    rows = [json.loads(l) for l in gzip.open(a.index, "rt")]
    jobs_ifc, jobs_db1 = load_jobs("ifc"), load_jobs("db1")
    tm = truth_map(rows)
    for e in [e for v in tm.values() for e in v]:
        e["input_key"] = input_key("ifc", e["ifc_id"], jobs_ifc)[0]
    json.dump(tm, open(os.path.join(a.out, "truth_map.json"), "w"), indent=1)
    rnd = random.Random(a.seed)
    def size_b(r): return "lt1MB" if (r.get("step_bytes") or 0) < 1e6 else "1-20MB" if (r.get("step_bytes") or 0) < 2e7 else "20-300MB" if (r.get("step_bytes") or 0) < 3e8 else "ge300MB"
    def strat(cands, n, key):
        g = collections.defaultdict(list)
        for r in cands: g[key(r)].append(r)
        for v in g.values(): rnd.shuffle(v)
        out = []; ks = sorted(g)
        while len(out) < n and any(g.values()):
            for k in ks:
                if g[k] and len(out) < n: out.append(g[k].pop())
        return out
    ifc = [r for r in rows if r["pipeline"] == "ifc" and r.get("step_key")]
    c1 = strat([r for r in ifc if r["class"] == 1], a.ifc_c1, lambda r: (size_b(r), "reused" if r.get("reused") else str(r.get("converter_code"))[-10:]))
    c2 = strat([r for r in ifc if r["class"] == 2], a.ifc_c2, lambda r: (size_b(r), ((r.get("needed_to_fix") or [{}])[0].get("key") or "none")))
    def job(r, pipe, jobs):
        ik, rk = input_key(pipe, r["id"], jobs)
        j = dict(pipeline=pipe, id=r["id"], cls=r["class"], step_key=r["step_key"], input_key=ik, record_key=rk, size=r.get("size"), step_bytes=r.get("step_bytes"),
                 reasons=[x.get("key") for x in r.get("needed_to_fix") or []])
        if pipe == "db1": j["truth_candidates"] = len(tm.get(r["id"], []))
        return j
    with cf.ThreadPoolExecutor(16) as ex:
        ifc_jobs = list(ex.map(lambda r: job(r, "ifc", jobs_ifc), c1 + c2))
        db1_jobs = list(ex.map(lambda r: job(r, "db1", jobs_db1), [r for r in rows if r["pipeline"] == "db1" and r.get("step_key")]))
    for nm, js in (("ifc_audit_jobs.jsonl", ifc_jobs), ("db1_jobs.jsonl", db1_jobs)):
        with open(os.path.join(a.out, nm), "w") as f:
            for j in js: f.write(json.dumps(j) + "\n")
        print(nm, len(js), "without input_key:", sum(1 for j in js if not j["input_key"]))
    print("truth_map models:", len(tm))


if __name__ == "__main__":
    main()
