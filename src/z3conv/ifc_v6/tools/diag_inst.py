#!/usr/bin/env python3
"""instance check: shared geometry (map frame) + MAPPED_ITEM instance for a product -> OCC validity per solid.
usage: diag_inst.py CONVERTER.py IFC GUID"""
import sys, os, collections, importlib.util, tempfile, json
spec = importlib.util.spec_from_file_location('v6', sys.argv[1]); V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
import ifcopenshell, ifcopenshell.util.unit, numpy as np
f = ifcopenshell.open(sys.argv[2]); g = sys.argv[3]
sc = ifcopenshell.util.unit.calculate_unit_scale(f) * 1000
tc = V.Transcoder(f, sc); rep = V.Repair(2)
p = f.by_guid(g)
items, rid = V.body_items(p)
pieces = tc.items_local(items[0].MappingSource.MappedRepresentation.Items)
bp = V.build_part(pieces, rep)
X, solids, surfaces, tags = bp
RT = V.inst_transform(tc, p, items[0])
print('transform', RT)
td = tempfile.mkdtemp()
sp = V.Spool(os.path.join(td, 'sp.bin'), 2)
sh = sp.emit(None, None, None, solids, surfaces, X, shared_key=1)
rec = V.PartRec(p.id(), g, p.Name, p.is_a(), 'tc', False); rec.inst = (1, RT[0], RT[1])
fr = V.emit_instance_rec(sp, rec, sh)
sp.close()
hdr, gents = V.header_text('diag')
fn = os.path.join(td, 'inst.step')
with open(fn, 'wb') as out, open(sp.path, 'rb') as s_:
    out.write(hdr.encode()); out.write(gents.encode()); out.write(s_.read()); out.write(V.TAIL.encode())
lf = os.path.join(td, 'l.json'); of = os.path.join(td, 'o.jsonl'); json.dump([fn], open(lf, 'w'))
V.verify_worker(lf, of)
for line in open(of): print(line.strip()[:600])
os.system("grep -n 'MAPPED_ITEM\\|REPRESENTATION_MAP\\|AXIS2_PLACEMENT_3D(.*#[0-9]*,#[0-9]*,#[0-9]*)' %s | tail -5" % fn)
