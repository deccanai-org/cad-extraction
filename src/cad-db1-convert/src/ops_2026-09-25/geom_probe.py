"""Tessellate every product that carries a boolean (cut) exactly as ifc2step5 does (ifcopenshell.geom, world coords,
welded vertices) and list the products whose triangulation has absurd vertices (OpenCASCADE's infinite bound is
2e100 m). READ-ONLY.  geom_probe.py model.ifc out.json [threads]"""
import json, math, sys, time
import ifcopenshell, ifcopenshell.geom

src, out = sys.argv[1], sys.argv[2]; th = int(sys.argv[3]) if len(sys.argv) > 3 else 16
f = ifcopenshell.open(src)
prods = set()
if len(sys.argv) > 4 and sys.argv[4] == "all":
    prods = {e for e in f.by_type("IfcProduct") if getattr(e, "Representation", None)}
for b in ([] if prods else list(f.by_type("IfcBooleanResult"))):
    stack = [b]; seen = set()
    while stack:
        x = stack.pop()
        if x.id() in seen: continue
        seen.add(x.id())
        for inv in f.get_inverse(x):
            if inv.is_a("IfcProduct"): prods.add(inv)
            else: stack.append(inv)
s = ifcopenshell.geom.settings()
for k, v in (("use-world-coords", True), ("weld-vertices", True)):
    try: s.set(k, v)
    except Exception: pass
t0 = time.time(); bad = []; n = 0
it = ifcopenshell.geom.iterator(s, f, th, include=list(prods))
if it.initialize():
    while True:
        sh = it.get(); vs = sh.geometry.verts; n += 1
        m = max((abs(v) for v in vs), default=0.0)
        if not math.isfinite(m) or m > 1e7:            # metres: 10,000 km
            e = f.by_guid(sh.guid)
            reps = [(r.RepresentationType, [i.is_a() for i in r.Items][:3], [str(x)[:160] for x in list(f.traverse(r.Items[0]))[:6]]) for r in e.Representation.Representations]
            bad.append(dict(guid=sh.guid, id=e.id(), name=sh.name, type=e.is_a(), reps=reps, max_abs_m=m if math.isfinite(m) else str(m),
                            verts=len(vs) // 3, bad_verts=sum(1 for i in range(0, len(vs), 3) if max(abs(vs[i]), abs(vs[i + 1]), abs(vs[i + 2])) > 1e7)))
        if not it.next(): break
res = dict(products_with_booleans=len(prods), tessellated=n, absurd=len(bad), secs=round(time.time() - t0), bad=bad)
json.dump(res, open(out, "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "bad"}), json.dumps(bad[:10]))
