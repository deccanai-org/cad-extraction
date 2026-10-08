"""Subprocess: decode a .db1 with the production decoder, write its IFC, mesh every element.
python -m db1stepverify.repro_worker DB1 OUT_IFC DECODER_DIR ENGINE OUT_JSON"""
import sys, os, json, time


def _numpy_compat():
    """The production decoder calls np.cross on 2-D vectors (numpy < 2.x returned the z-component); numpy >= 2.x
    raises. Restore the old result for that one case so the decoder runs unmodified on a current numpy."""
    import numpy as np
    if getattr(np.cross, "_db1v_shim", False): return False
    orig = np.cross
    def cross(a, b, *args, **kw):
        a2, b2 = np.asarray(a), np.asarray(b)
        if not args and not kw and a2.shape[-1:] == (2,) and b2.shape[-1:] == (2,):
            return a2[..., 0] * b2[..., 1] - a2[..., 1] * b2[..., 0]
        return orig(a, b, *args, **kw)
    cross._db1v_shim = True; np.cross = cross
    return True


def main():
    db1, out_ifc, dec, engine, out_json = sys.argv[1:6]
    shim = _numpy_compat()
    sys.path.insert(0, dec)
    from db1step import convert
    cat = json.load(open(os.path.join(dec, "tekla_profiles.json")))
    layouts = json.load(open(os.path.join(dec, "layouts.json")))
    lay = (layouts.get(engine) or {}).get("layout")
    variants = [v["layout"] for v in layouts.values() if v.get("layout")]
    t0 = time.time()
    st = convert(db1, out_ifc, cat, lay, variants, allow_full=False)
    import numpy
    res = dict(status=st.get("status"), decode_secs=round(time.time() - t0, 1), numpy=numpy.__version__, numpy_cross_2d_shim=shim,
               stats={k: v for k, v in st.items() if k not in ("layout",)})
    if st.get("status") == "ok" and os.path.exists(out_ifc):
        from db1stepverify.ifcmesh import mesh_ifc
        t1 = time.time()
        els, _, _ = mesh_ifc(out_ifc, want_tris=False)
        res["elements"] = els; res["mesh_secs"] = round(time.time() - t1, 1)
        import ifcopenshell
        f = ifcopenshell.open(out_ifc)
        res["ifc_products"] = len(f.by_type("IfcBeam")) + len(f.by_type("IfcPlate"))
    json.dump(res, open(out_json, "w"), default=str)


if __name__ == "__main__":
    main()
