#!/usr/bin/env python3
"""Per-root OCC read-back exactly like step_check.py: for every root (label = PRODUCT_DEFINITION #id) list its solids
as [volume, n_shells, valid]. usage: occ_roots.py FILE.step OUT.jsonl"""
import sys, json
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_SHELL
from OCC.Core.GProp import GProp_GProps
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.BRepCheck import BRepCheck_Analyzer
import re
# PRODUCT_DEFINITION #id -> PRODUCT id string (GlobalId for the current writer, name for the old one) - stable key
prod, pdf, pdn = {}, {}, {}
for line in open(sys.argv[1], encoding='latin-1'):
    if line.startswith('#') and 'PRODUCT' in line:
        m = re.match(r"#(\d+)=(PRODUCT|PRODUCT_DEFINITION_FORMATION|PRODUCT_DEFINITION)\((.*)\);", line.strip())
        if not m:
            continue
        k, t, b = int(m.group(1)), m.group(2), m.group(3)
        if t == 'PRODUCT':
            q = re.findall(r"'((?:[^']|'')*)'", b); prod[k] = (q[0] if q else '') + '|' + (q[1] if len(q) > 1 else '')
        elif t == 'PRODUCT_DEFINITION_FORMATION':
            pdf[k] = int(re.findall(r'#(\d+)', b)[-1])
        else:
            pdn[k] = int(re.findall(r'#(\d+)', b)[0])
r = STEPControl_Reader(); assert r.ReadFile(sys.argv[1]) == IFSelect_RetDone
model = r.WS().Model(); n = r.NbRootsForTransfer(); fo = open(sys.argv[2], 'w')
def items(sh, t):
    e = TopExp_Explorer(sh, t); o = []
    while e.More(): o.append(e.Current()); e.Next()
    return o
for i in range(1, n + 1):
    lab = model.StringLabel(r.RootForTransfer(i)).ToCString()
    if not r.TransferRoot(i):
        fo.write(json.dumps({'i': i, 'pd': int(lab.lstrip('#')), 'key': prod.get(pdf.get(pdn.get(int(lab.lstrip('#'))))), 'empty': True}) + '\n'); continue
    sh = r.Shape(r.NbShapes()); sols = []
    for s in items(sh, TopAbs_SOLID):
        g = GProp_GProps()
        try:
            brepgprop.VolumeProperties(s, g); v = g.Mass()
        except Exception:
            v = None
        sols.append([v, len(items(s, TopAbs_SHELL)), bool(BRepCheck_Analyzer(s).IsValid())])
    fo.write(json.dumps({'i': i, 'pd': int(lab.lstrip('#')), 'key': prod.get(pdf.get(pdn.get(int(lab.lstrip('#'))))), 'solids': sols}) + '\n')
