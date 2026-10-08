"""Regenerate the STEP of DB1 conversions whose published output holds a vertex at the geometry kernel's infinite
bound (OpenCASCADE 2e100 m), from the model just re-decoded by the current worker code (coord_probe.py left
/opt/ph/probe/<sha12>/model.ifc + convert.json). Same converter, flags and checks as the worker's STEP stage.
Stages the new STEP + candidate result under _control/packaging/step_v1_db1_posthoc/fix/ (nothing published).
  regen_step.py sha [sha ...]"""
import json, os, re, subprocess, sys, time

B = "annotationprod"; R = "cad-disk-extract"; WORK = "/opt/db1v2"; PY84 = "/opt/ifc84/bin/python"
FIX = f"s3://{B}/{R}/_control/packaging/step_v1_db1_posthoc/fix"
ABSURD = re.compile(rb"CARTESIAN_POINT\('',\([^)]*[eE]\+?(1[0-9]|[2-9][0-9]|[1-9][0-9][0-9])[,)]")


def cp(a, b): subprocess.run(["aws", "s3", "cp", "--region", "ap-south-1", "--quiet", a, b], check=True)


def count(path, pats):
    c = {p: 0 for p in pats}; bad = 0
    with open(path, "rb") as fh:
        for ln in fh:
            for p in pats:
                if p in ln: c[p] += 1
            if b"CARTESIAN_POINT" in ln and ABSURD.search(ln): bad += 1
    return c, bad


for sha in sys.argv[1:]:
    d = f"/opt/ph/probe/{sha[:12]}"; ifc = f"{d}/model.ifc"; stp = f"{d}/fixed.stp"
    cp(f"s3://{B}/{R}/_state/db1-v2/results/{sha}.json", f"{d}/old_result.json")
    old = json.load(open(f"{d}/old_result.json")); cs = json.load(open(f"{d}/convert.json"))
    t = time.time()
    rc = subprocess.run([PY84, f"{WORK}/ifc2step5.py", ifc, stp, "--mode", "hybrid", "--prec", "2", "--threads", "4"],
                        stdout=open(f"{d}/regen.log", "w"), stderr=subprocess.STDOUT, timeout=21600).returncode
    st = json.load(open(stp + ".stats.json")) if os.path.exists(stp + ".stats.json") else {}
    m, bad = count(stp, [b"FACETED_BREP(", b"CLOSED_SHELL(", b"ADVANCED_FACE", b"TESSELLATED", b"TRIANGULATED_FACE_SET"])
    m = {k.decode().rstrip("("): v for k, v in m.items()}
    head = open(stp, errors="replace").read(4000)
    flavour = m["ADVANCED_FACE"] == 0 and m["TESSELLATED"] == 0 and m["TRIANGULATED_FACE_SET"] == 0 and "AUTOMOTIVE_DESIGN" in head
    bb = st.get("bbox") or []
    ok = rc == 0 and flavour and bad == 0 and bb and max(abs(v) for v in bb) < 1e10 and m["FACETED_BREP"] > 0
    rec = dict(old)
    rec.update(convert={k: v for k, v in cs.items() if k != "layout"}, layout=cs.get("layout"), arc_writer=cs.get("arc_writer"),
               arc_stats=cs.get("arc_stats"), step_rc=rc, step_sec=round(time.time() - t, 1), step_stats=st, out_bytes=os.path.getsize(stp),
               markers=m, flavour_ok=flavour, readback={"skipped": "output >= 64 MB"} if os.path.getsize(stp) >= (64 << 20) else old.get("readback"),
               regenerated=dict(at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                reason="previous output held tessellated vertices at the geometry kernel's infinite bound (2e100 m); "
                                       "re-decoded with the same code and re-tessellated: no such vertex",
                                previous=dict(out_bytes=old.get("out_bytes"), bbox=(old.get("step_stats") or {}).get("bbox"),
                                              parts=(old.get("step_stats") or {}).get("parts"), host=old.get("host"))))
    summary = dict(sha=sha, rc=rc, ok=bool(ok), absurd_points=bad, flavour_ok=flavour, parts=st.get("parts"), parts_before=(old.get("step_stats") or {}).get("parts"),
                   written=cs.get("written"), written_before=(old.get("convert") or {}).get("written"), bbox=bb, out_bytes=os.path.getsize(stp),
                   out_bytes_before=old.get("out_bytes"), faceted_breps=m["FACETED_BREP"])
    json.dump(rec, open(f"{d}/new_result.json", "w"), indent=1, default=str)
    json.dump(summary, open(f"{d}/regen_summary.json", "w"), indent=1)
    if ok:
        cp(stp, f"{FIX}/{sha}.stp"); cp(f"{d}/new_result.json", f"{FIX}/{sha}.result.json")
    cp(f"{d}/regen_summary.json", f"{FIX}/{sha}.summary.json")
    print(json.dumps(summary), flush=True)
