"""Re-decode DB1 files exactly as the worker does (convert_one.py -> model.ifc) and list every written part whose
geometry carries far or absurd values: placement origin (world), profile / outline points, extrusion depth.
READ-ONLY against S3 except the probe report. Runs on a fleet host with the fleet's occ python.
  coord_probe.py jobs.json  -> _control/packaging/step_v1_db1_posthoc/probe/<sha12>.json"""
import json, math, os, subprocess, sys, time, collections
import ifcopenshell, ifcopenshell.util.placement as up

B = "annotationprod"; R = "cad-disk-extract"; W = "/opt/ph/probe"; WORK = "/opt/db1v2"
PY = f"{WORK}/mamba/envs/occ/bin/python"
def cp(a, b): subprocess.run(["aws", "s3", "cp", "--region", "ap-south-1", "--quiet", a, b], check=True)
jobs = json.load(open(sys.argv[1]))
cp(f"s3://{B}/{R}/_control/db1-v2/layouts.json", "/opt/ph/layouts.json"); layouts = json.load(open("/opt/ph/layouts.json"))


def vals(ent, f):
    """every coordinate / length number under a representation item"""
    out = []
    for x in f.traverse(ent):
        t = x.is_a()
        if t == "IfcCartesianPoint": out += list(x.Coordinates)
        elif t == "IfcCartesianPointList2D" or t == "IfcCartesianPointList3D": out += [v for p in x.CoordList for v in p]
        elif t == "IfcExtrudedAreaSolid": out.append(x.Depth)
        elif x.is_a("IfcParameterizedProfileDef"):
            for i in range(x.__len__()):
                v = x[i]
                if isinstance(v, float): out.append(v)
    return out


for j in jobs:
    sha = j["sha"]; d = f"{W}/{sha[:12]}"; os.makedirs(d, exist_ok=True)
    t0 = time.time()
    db1 = f"{d}/in.db1"; ifc = f"{d}/model.ifc"; stats = f"{d}/convert.json"
    cp(f"s3://{B}/{j['key']}", db1)
    json.dump(layouts.get(j["engine"], {}).get("layout"), open(f"{d}/layout.json", "w"))
    json.dump([v["layout"] for v in layouts.values() if v.get("layout")], open(f"{d}/variants.json", "w"))
    rc = subprocess.run([PY, f"{WORK}/src/convert_one.py", db1, ifc, f"{WORK}/tekla_profiles.json", f"{d}/layout.json", stats, f"{d}/variants.json"],
                        capture_output=True, text=True, timeout=7200).returncode
    cs = json.load(open(stats)) if os.path.exists(stats) else {}
    rep = {"sha": sha, "rc": rc, "status": cs.get("status"), "members": cs.get("members"), "written": cs.get("written"), "convert_sec": round(time.time() - t0)}
    if rc == 0 and os.path.exists(ifc):
        f = ifcopenshell.open(ifc)
        rows = []
        for e in f.by_type("IfcProduct"):
            if not getattr(e, "Representation", None): continue
            try: org = [float(v) for v in up.get_local_placement(e.ObjectPlacement)[:3, 3]]
            except Exception: org = [float("nan")] * 3
            loc = []
            for r in e.Representation.Representations:
                for it in r.Items: loc += vals(it, f)
            mloc = max((abs(v) for v in loc), default=0.0)
            morg = max(abs(v) for v in org)
            finite = all(math.isfinite(v) for v in org + loc)
            rows.append((max(mloc, morg), e.Name, e.is_a(), [round(v, 1) for v in org], mloc, finite))
        rows.sort(key=lambda r: -r[0] if math.isfinite(r[0]) else -1e308)
        bins = collections.Counter("nonfinite" if not r[5] else ">1e12" if r[0] > 1e12 else ">1e9" if r[0] > 1e9 else ">1e7" if r[0] > 1e7 else "ok" for r in rows)
        rep.update(products=len(rows), bins=dict(bins),
                   worst=[dict(max=r[0], name=r[1], type=r[2], origin=r[3], max_local=r[4], finite=r[5]) for r in rows[:25]])
    json.dump(rep, open(f"{d}/probe.json", "w"), default=str, indent=1); cp(f"{d}/probe.json", f"s3://{B}/{R}/_control/packaging/step_v1_db1_posthoc/probe/{sha[:12]}.json")
    print(json.dumps({k: rep.get(k) for k in ("sha", "rc", "status", "members", "written", "products", "bins", "convert_sec")}), flush=True)
