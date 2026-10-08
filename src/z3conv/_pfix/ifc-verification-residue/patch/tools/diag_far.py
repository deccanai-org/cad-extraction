#!/usr/bin/env python3
"""Why does a part fail every fallback level? For each GUID: build the part exactly as the converter does (transcoder
and/or kernel polyhedral / triangle mesh), write it as a one-part STEP (a) in place and (b) translated by a whole-metre
offset (geometry identical, only the coordinates' magnitude changes), read both back with the converter's own
verify_worker (step_check checks) and list the BRepCheck statuses of failing sub-shapes.
usage: diag_far.py CONV.py IFC GUID [GUID ...]"""
import sys, os, json, math, tempfile, importlib.util, collections
import numpy as np
spec = importlib.util.spec_from_file_location('conv', sys.argv[1]); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.unit
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[2])
sc = float(ifcopenshell.util.unit.calculate_unit_scale(f)) * 1000.0
tc = M.Transcoder(f, sc)
hdr, gents = M.header_text('diag')


def occ_detail(path):
    """per root: BRepCheck statuses of failing sub-shapes (first 12)"""
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.BRepCheck import BRepCheck_Analyzer, BRepCheck_ListIteratorOfListOfStatus
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_VERTEX, TopAbs_EDGE, TopAbs_WIRE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    import OCC.Core.BRepCheck as BC
    names = {getattr(BC, n): n for n in dir(BC) if n.startswith('BRepCheck_') and isinstance(getattr(BC, n), int)}
    r = STEPControl_Reader(); r.ReadFile(path); r.TransferRoots(); sh = r.OneShape()
    an = BRepCheck_Analyzer(sh)
    out = {'valid': bool(an.IsValid()), 'bad': collections.Counter()}
    for typ, tn in ((TopAbs_VERTEX, 'V'), (TopAbs_EDGE, 'E'), (TopAbs_WIRE, 'W'), (TopAbs_FACE, 'F'), (TopAbs_SHELL, 'SH'), (TopAbs_SOLID, 'SO')):
        ex = TopExp_Explorer(sh, typ)
        while ex.More():
            s = ex.Current()
            res = an.Result(s)
            if res is not None:
                try:
                    it = BRepCheck_ListIteratorOfListOfStatus(res.Status())
                    while it.More():
                        v = it.Value()
                        if v != 0:
                            out['bad'][tn + ':' + names.get(v, str(v))] += 1
                        it.Next()
                except Exception as e:
                    out['bad']['iter_err'] += 1
            ex.Next()
    out['bad'] = dict(out['bad'])
    # same shape, exact whole-metre translation towards the origin (copy: geometry recomputed), checked again
    try:
        from OCC.Core.Bnd import Bnd_Box
        from OCC.Core.BRepBndLib import brepbndlib
        from OCC.Core.gp import gp_Trsf, gp_Vec
        from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Transform
        from OCC.Core.GProp import GProp_GProps
        from OCC.Core.BRepGProp import brepgprop
        from OCC.Core.BRep import BRep_Tool
        from OCC.Core.TopoDS import topods
        b = Bnd_Box(); brepbndlib.Add(sh, b, False); bb = b.Get()
        off = [math.floor(v / 1000.0) * 1000.0 for v in bb[:3]]
        t = gp_Trsf(); t.SetTranslation(gp_Vec(-off[0], -off[1], -off[2]))
        cp = BRepBuilderAPI_Transform(sh, t, True).Shape()
        an2 = BRepCheck_Analyzer(cp)
        g = GProp_GProps(); brepgprop.VolumeProperties(cp, g)
        out['translated_copy'] = {'offset_mm': off, 'valid': bool(an2.IsValid()), 'volume': g.Mass()}
        tv = 0.0; ex = TopExp_Explorer(sh, TopAbs_VERTEX)
        while ex.More():
            tv = max(tv, BRep_Tool.Tolerance(topods.Vertex(ex.Current()))); ex.Next()
        te = 0.0; ex = TopExp_Explorer(sh, TopAbs_EDGE)
        while ex.More():
            te = max(te, BRep_Tool.Tolerance(topods.Edge(ex.Current()))); ex.Next()
        out['max_tol_vertex'] = tv; out['max_tol_edge'] = te
    except Exception as e:
        out['translated_copy'] = 'err %s' % e
    return out


def write_and_check(name, gid, bp, shift, mapped=False):
    X, solids, surfaces, tags = bp
    Xs = X - shift if shift is not None else X
    td = tempfile.mkdtemp(prefix='diagfar_')
    sp = M.Spool(os.path.join(td, 's.bin'), 2)
    if mapped:
        # local-frame geometry written once + placed by a pure translation (MAPPED_ITEM), absolute position unchanged
        sh = sp.emit(None, None, None, solids, surfaces, Xs, shared_key='far')
        fr = sp.emit_instance(name, gid, 'diag', sh, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [float(v) for v in shift])
    else:
        fr = sp.emit(name, gid, 'diag', solids, surfaces, Xs)
    sp.close()
    out = os.path.join(td, 'p.step')
    with open(out, 'wb') as o, open(sp.path, 'rb') as s_:
        o.write(hdr.encode()); o.write(gents.encode()); o.write(s_.read()); o.write(M.TAIL.encode())
    lf = os.path.join(td, 'l.json'); of = os.path.join(td, 'o.jsonl'); json.dump([out], open(lf, 'w'))
    M.verify_worker(lf, of)
    r = json.loads(open(of).readline())
    ok, why = M.judge(r, fr)
    res = {'verdict': 'pass' if ok else why, 'occ_valid': r.get('valid'), 'occ_vols': r.get('vols'), 'mesh_vol': round(fr.vol, 3),
           'solids': fr.nsol, 'surfaces': fr.nsurf, 'faces': fr.nfaces}
    try:
        d_ = occ_detail(out)
        res['brepcheck'] = d_['bad']; res['translated_copy'] = d_.get('translated_copy')
        res['max_tol'] = [d_.get('max_tol_vertex'), d_.get('max_tol_edge')]
    except Exception as e:
        res['brepcheck'] = 'err %s' % e
    return res


for g in sys.argv[3:]:
    p = f.by_guid(g)
    rec = {'gid': g, 'cls': p.is_a(), 'name': p.Name}
    items, rid = M.body_items(p)
    rec['items'] = [it.is_a() for it in items or []]
    rec['openings'] = len(getattr(p, 'HasOpenings', None) or [])
    builds = {}
    try:
        pieces = tc.product(p, items) if items else None
        if pieces is not None:
            builds['tc'] = M.build_part(pieces, M.Repair(2))
    except Exception as e:
        rec['tc_err'] = str(e)[:200]
    for mode in ('poly', 'tri'):
        try:
            s, _, m = M.kernel_settings(mode)
            shp = ifcopenshell.geom.create_shape(s, p)
            V, faces, iids = M.kernel_geometry(shp.geometry, m)
            builds['kernel_' + mode] = M.build_part(M.kernel_pieces(f, V, faces, iids), M.Repair(2))
        except Exception as e:
            rec['kernel_%s_err' % mode] = str(e)[:200]
    for k, bp in builds.items():
        if bp is None or bp == 'corrupt':
            rec[k] = str(bp); continue
        X = bp[0]
        lo = X.min(0)
        shift = np.floor(lo / 1000.0) * 1000.0     # whole metres: every grid point stays a grid point
        rec[k] = {'bbox_min_mm': [round(v, 2) for v in lo.tolist()], 'tags': sorted(bp[3]),
                  'in_place': write_and_check(p.Name, g, bp, None), 'shifted': write_and_check(p.Name, g, bp, shift),
                  'mapped_translation': write_and_check(p.Name, g, bp, shift, mapped=True)}
    print(json.dumps(rec, default=str), flush=True)
