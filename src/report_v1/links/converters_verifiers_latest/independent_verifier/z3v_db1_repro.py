"""Reproduce stage for db1stepverify with OUR production decoder (data-3 DB1 kit, code r), replacing the verifier's
repro_worker (which calls the Disk-1/2 db1-v2 decoder's db1step.convert directly). Same output JSON as repro_worker:
dict(status, decode_secs, stats, elements=[{guid,type,name,profile,volume_mm3,centroid,bbox}], ifc_products, ...).

  worker:  python z3v_db1_repro.py DB1 OUT_IFC KIT_DIR ENGINE OUT_JSON [DECODER_PY]
  decode:  python z3v_db1_repro.py --decode <convert_one.py args...>   (internal: numpy shim + runpy convert_one.py)

The decode runs exactly as db1/worker.py runs it: convert_one.py DB1 IFC tekla_profiles.json layout.json stats.json
variants.json (profile overlay + per-model bolt catalog applied inside convert_one / db1step), and again with
DB1_FULL_DISCOVERY=1 when the fast paths return deferred_layout."""
import os, sys, json, time, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def _decode_main(argv):
    sys.path.insert(0, HERE)
    from db1stepverify.repro_worker import _numpy_compat        # the verifier's own numpy>=2 np.cross(2-D) shim
    shim = _numpy_compat()
    conv = argv[0]; sys.argv = argv
    sys.path.insert(0, os.path.dirname(os.path.abspath(conv)))
    os.environ["Z3V_NUMPY_SHIM"] = "1" if shim else "0"
    import runpy
    runpy.run_path(conv, run_name="__main__")


def main():
    db1, out_ifc, kit, engine, out_json = sys.argv[1:6]
    dpy = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else sys.executable
    wd = os.path.dirname(os.path.abspath(out_ifc))
    layouts = json.load(open(os.path.join(kit, "layouts.json")))
    lp = os.path.join(wd, "repro_layout.json"); json.dump((layouts.get(engine) or {}).get("layout"), open(lp, "w"))
    vp = os.path.join(wd, "repro_variants.json"); json.dump([v["layout"] for v in layouts.values() if v.get("layout")], open(vp, "w"))
    stats = os.path.join(wd, "repro_convert.json")
    cmd = [dpy, os.path.abspath(__file__), "--decode", os.path.join(kit, "convert_one.py"), db1, out_ifc,
           os.path.join(kit, "tekla_profiles.json"), lp, stats, vp]
    t0 = time.time(); full = False
    log = open(os.path.join(wd, "repro_decode.log"), "w")
    p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=kit)
    st = json.load(open(stats)) if os.path.exists(stats) else {}
    if p.returncode == 0 and st.get("status") == "deferred_layout":
        full = True
        p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=kit, env=dict(os.environ, DB1_FULL_DISCOVERY="1"))
        st = json.load(open(stats)) if os.path.exists(stats) else {}
    import numpy
    res = dict(status=st.get("status") or f"decoder rc {p.returncode}", decode_secs=round(time.time() - t0, 1), full_discovery=full,
               decoder_python=dpy, numpy=numpy.__version__, stats={k: v for k, v in st.items() if k not in ("layout", "trace")})
    if st.get("trace"): res["trace"] = st["trace"][-1500:]
    if st.get("status") == "ok" and os.path.exists(out_ifc):
        sys.path.insert(0, HERE)
        from db1stepverify.ifcmesh import mesh_ifc
        t1 = time.time()
        els, _, _ = mesh_ifc(out_ifc, want_tris=False, threads=int(os.environ.get("Z3V_THREADS", "2")))
        res["elements"] = els; res["mesh_secs"] = round(time.time() - t1, 1)
        import ifcopenshell
        f = ifcopenshell.open(out_ifc)
        res["ifc_products"] = len(f.by_type("IfcBeam")) + len(f.by_type("IfcPlate"))
    json.dump(res, open(out_json, "w"), default=str)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--decode":
        _decode_main(sys.argv[2:])
    else:
        main()
