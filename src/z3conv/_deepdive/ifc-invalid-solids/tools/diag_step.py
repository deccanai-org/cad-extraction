#!/usr/bin/env python3
"""Diagnose invalid solids in a STEP file exactly as step_check.py sees them (STEPControl_Reader, root by root),
and list the BRepCheck statuses of every failing sub-shape.

usage: diag_step.py FILE.step OUT.json [--max-roots N] [--dump-dir DIR]
Per invalid solid: product id/name, #faces, BRepCheck statuses by sub-shape type (counts), shell closed/free edges,
volume, and (with --dump-dir) the solid as BREP for later replay.
"""
import sys, os, json, re, argparse, collections, time
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer, topexp
from OCC.Core.TopAbs import (TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_EDGE, TopAbs_WIRE, TopAbs_VERTEX,
                             TopAbs_COMPOUND)
from OCC.Core.BRepCheck import BRepCheck_Analyzer, BRepCheck_Status
from OCC.Core.TopTools import TopTools_IndexedMapOfShape
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepTools import breptools
from OCC.Core.ShapeAnalysis import ShapeAnalysis_FreeBounds

STATUS = {}
for n in dir(BRepCheck_Status):
    if n.startswith('BRepCheck_'):
        STATUS[getattr(BRepCheck_Status, n)] = n[len('BRepCheck_'):]
TYPES = [(TopAbs_VERTEX, 'vertex'), (TopAbs_EDGE, 'edge'), (TopAbs_WIRE, 'wire'), (TopAbs_FACE, 'face'),
         (TopAbs_SHELL, 'shell'), (TopAbs_SOLID, 'solid')]


def sname(s):
    try:
        return STATUS.get(s, str(s))
    except Exception:
        return str(s)


def statuses(shape):
    """{ 'type:Status': count } over all sub-shapes, including contextual (edge-in-face etc.) results"""
    an = BRepCheck_Analyzer(shape)
    out = collections.Counter()
    valid = an.IsValid()
    for t, tn in TYPES:
        m = TopTools_IndexedMapOfShape()
        topexp.MapShapes(shape, t, m)
        for i in range(1, m.Size() + 1):
            sub = m.FindKey(i)
            r = an.Result(sub)
            if r is None:
                continue
            try:
                for s in r.Status():
                    nm = sname(s)
                    if nm != 'NoError':
                        out[f'{tn}:{nm}'] += 1
            except Exception as e:
                out[f'{tn}:err'] += 1
            try:
                r.InitContextIterator()
                while r.MoreShapeInContext():
                    for s in r.StatusOnShape():
                        nm = sname(s)
                        if nm != 'NoError':
                            out[f'{tn}@ctx:{nm}'] += 1
                    r.NextShapeInContext()
            except Exception:
                pass
    return valid, out


def count(shape, t):
    m = TopTools_IndexedMapOfShape(); topexp.MapShapes(shape, t, m); return m.Size()


def free_edges(shape):
    fb = ShapeAnalysis_FreeBounds(shape, 1e-7, False, False)
    c = fb.GetClosedWires(); o = fb.GetOpenWires()
    return count(c, TopAbs_EDGE) + count(o, TopAbs_EDGE)


def volume(s):
    g = GProp_GProps(); brepgprop.VolumeProperties(s, g); return g.Mass()


def products(path):
    """root SDR/PD label -> (id, name) via a cheap text pass (same chain as step_check)"""
    ent_re = re.compile(r"^#(\d+)\s*=\s*([A-Z_0-9]+)\s*\((.*)\)\s*;\s*$", re.S)
    prod, pdf, pd, pds, sdr = {}, {}, {}, {}, {}
    for line in open(path, encoding='latin-1'):
        if 'PRODUCT' not in line and 'SHAPE_DEFINITION_REPRESENTATION' not in line:
            continue
        m = ent_re.match(line.strip())
        if not m:
            continue
        eid, typ, body = int(m.group(1)), m.group(2), m.group(3)
        refs = [int(x) for x in re.findall(r'#(\d+)', body)]
        if typ == 'PRODUCT':
            s = re.findall(r"'((?:[^']|'')*)'", body); prod[eid] = (s[0] if s else '', s[1] if len(s) > 1 else '')
        elif typ.startswith('PRODUCT_DEFINITION_FORMATION'):
            pdf[eid] = refs[-1]
        elif typ.startswith('PRODUCT_DEFINITION') and typ not in ('PRODUCT_DEFINITION_SHAPE', 'PRODUCT_DEFINITION_CONTEXT'):
            pd[eid] = refs[0]
        elif typ == 'PRODUCT_DEFINITION_SHAPE':
            pds[eid] = refs[0]
        elif typ == 'SHAPE_DEFINITION_REPRESENTATION':
            sdr[eid] = refs[0]

    def of(eid):
        if eid in sdr:
            eid = pds.get(sdr[eid])
        return prod.get(pdf.get(pd.get(eid)))
    return of


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('out')
    ap.add_argument('--max-roots', type=int, default=0); ap.add_argument('--dump-dir')
    a = ap.parse_args()
    t0 = time.time()
    of = products(a.step)
    r = STEPControl_Reader()
    assert r.ReadFile(a.step) == IFSelect_RetDone
    model = r.WS().Model()
    n = r.NbRootsForTransfer()
    tot = collections.Counter(); agg = collections.Counter(); bad = []
    for i in range(1, n + 1):
        if a.max_roots and i > a.max_roots:
            break
        ent = r.RootForTransfer(i)
        try:
            eid = int(model.StringLabel(ent).ToCString().lstrip('#'))
        except Exception:
            eid = None
        p = of(eid) if eid else None
        if not r.TransferRoot(i):
            tot['empty'] += 1; continue
        sh = r.Shape(r.NbShapes())
        ex = TopExp_Explorer(sh, TopAbs_SOLID); sols = []
        while ex.More():
            sols.append(ex.Current()); ex.Next()
        tot['roots'] += 1; tot['solids'] += len(sols)
        tot['roots_multi_solid'] += len(sols) > 1
        for k, s in enumerate(sols):
            ok = BRepCheck_Analyzer(s).IsValid()
            if ok:
                tot['valid'] += 1; continue
            tot['invalid'] += 1
            v, st = statuses(s)
            agg.update(st)
            rec = {'root': i, 'eid': eid, 'pid': p[0] if p else None, 'name': p[1] if p else None, 'solid_idx': k, 'n_solids_in_root': len(sols),
                   'faces': count(s, TopAbs_FACE), 'shells': count(s, TopAbs_SHELL), 'free_edges': free_edges(s),
                   'volume': round(volume(s), 3), 'status': dict(st)}
            if a.dump_dir:
                os.makedirs(a.dump_dir, exist_ok=True)
                fn = os.path.join(a.dump_dir, f'r{i}_s{k}.brep'); breptools.Write(s, fn); rec['brep'] = fn
            bad.append(rec)
    out = {'file': os.path.basename(a.step), 'totals': dict(tot), 'status_agg': dict(agg.most_common()),
           'sec': round(time.time() - t0, 1), 'invalid': bad}
    json.dump(out, open(a.out, 'w'), indent=1)
    print(json.dumps({k: out[k] for k in ('file', 'totals', 'status_agg', 'sec')}))


if __name__ == '__main__':
    main()
