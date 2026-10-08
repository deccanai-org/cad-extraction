#!/usr/bin/env python3
"""Far-from-origin parts: which READ-BACK / CHECK variant sees the written solid as valid? (geometry never moved)
For each GUID the part is built as the converter builds it (kernel polyhedral) and written as
  P = in place (absolute coordinates), Q = local frame + MAPPED_ITEM pure translation (absolute position unchanged)
and checked with
  a) default reader + BRepCheck on the root shape (= step_check today)
  b) Q only: BRepCheck / volume on the root shape with its top-level location stripped (the shape in its own frame)
  c) tolerance floor: ShapeFix_ShapeTolerance.LimitTolerance(sh, tmin) with tmin = 8 ulp of the largest coordinate,
     then BRepCheck (a tolerance that the coordinates' own precision can honour)
  d) reader precision: read.precision.mode=1, read.precision.val=1e-5 (healing basis), BRepCheck
usage: diag_far2.py CONV.py IFC GUID [GUID ...]"""
import sys, os, json, math, tempfile, importlib.util
import numpy as np
spec = importlib.util.spec_from_file_location('conv', sys.argv[1]); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.unit
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.BRepCheck import BRepCheck_Analyzer
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.ShapeFix import ShapeFix_ShapeTolerance
from OCC.Core.TopAbs import TopAbs_SHAPE
from OCC.Core.Interface import Interface_Static
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[2])
hdr, gents = M.header_text('diag')
OUT = os.environ.get('DIAG_OUT', tempfile.mkdtemp(prefix='far2_'))
os.makedirs(OUT, exist_ok=True)


def write(name, gid, bp, mapped, fn):
    X, solids, surfaces, tags = bp
    lo = X.min(0)
    shift = np.floor(lo / 1000.0) * 1000.0
    sp = M.Spool(fn + '.spool', 2)
    if mapped:
        sh = sp.emit(None, None, None, solids, surfaces, X - shift, shared_key='far')
        fr = sp.emit_instance(name, gid, 'diag', sh, [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]], [float(v) for v in shift])
    else:
        fr = sp.emit(name, gid, 'diag', solids, surfaces, X)
    sp.close()
    with open(fn, 'wb') as o, open(fn + '.spool', 'rb') as s_:
        o.write(hdr.encode()); o.write(gents.encode()); o.write(s_.read()); o.write(M.TAIL.encode())
    return fr


def read(fn, prec=None):
    if prec is not None:
        Interface_Static.SetIVal('read.precision.mode', 1); Interface_Static.SetRVal('read.precision.val', prec)
    else:
        Interface_Static.SetIVal('read.precision.mode', 0)
    r = STEPControl_Reader(); r.ReadFile(fn)
    r.TransferRoot(1)
    return r.Shape(r.NbShapes())


def check(sh):
    v = bool(BRepCheck_Analyzer(sh).IsValid())
    g = GProp_GProps(); brepgprop.VolumeProperties(sh, g)
    return {'valid': v, 'vol': round(g.Mass(), 4)}


for gid in sys.argv[3:]:
    p = f.by_guid(gid)
    src = os.environ.get('DIAG_SRC', 'kernel')
    if src == 'tc':
        sc = float(ifcopenshell.util.unit.calculate_unit_scale(f)) * 1000.0
        items, _ = M.body_items(p)
        bp = M.build_part(M.Transcoder(f, sc).product(p, items), M.Repair(2))
    else:
        s, _, m = M.kernel_settings('poly')
        shp = ifcopenshell.geom.create_shape(s, p)
        V, faces, iids = M.kernel_geometry(shp.geometry, m)
        bp = M.build_part(M.kernel_pieces(f, V, faces, iids), M.Repair(2))
    res = {'gid': gid, 'name': p.Name, 'src': src, 'mesh_vol': round(sum(x.vol for x in bp[1]), 4), 'solids': len(bp[1]), 'surfaces': len(bp[2])}
    P = os.path.join(OUT, gid.replace('$', '_') + '_P.step'); Q = os.path.join(OUT, gid.replace('$', '_') + '_Q.step')
    write(p.Name, gid, bp, False, P)
    variants = (('P', P),)
    if os.environ.get('DIAG_Q', '1') == '1':
        write(p.Name, gid, bp, True, Q); variants = (('P', P), ('Q', Q))
    for tag, fn in variants:
        sh = read(fn)
        res[tag + '_a_default'] = check(sh)
        if tag == 'Q':
            res['Q_b_location_stripped'] = check(sh.Located(TopLoc_Location()))
            res['Q_b_has_location'] = not sh.Location().IsIdentity()
        b = Bnd_Box(); brepbndlib.Add(sh, b, False); bb = b.Get()
        mag = max(abs(x) for x in bb)
        tmin = max(1e-7, 8 * mag * 2.220446049250313e-16)
        sh2 = read(fn)
        ShapeFix_ShapeTolerance().LimitTolerance(sh2, tmin, 0.0, TopAbs_SHAPE)
        res[tag + '_c_tolerance_floor'] = dict(check(sh2), tmin=tmin)
        sh3 = read(fn, prec=1e-5)
        res[tag + '_d_reader_prec_1e-5'] = check(sh3)
    print(json.dumps(res), flush=True)
