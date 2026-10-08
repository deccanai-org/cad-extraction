#!/usr/bin/env python3
"""find_culprit.py CONV IFC SKIPFILE - create_shape (converter's polyhedral settings) product by product, printing the id
before each call (the last line before a kill / timeout names the culprit); ids in SKIPFILE are skipped"""
import sys, os, time, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
spec = importlib.util.spec_from_file_location('v6', sys.argv[1])
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[2])
skip = set(open(sys.argv[3]).read().split()) if os.path.exists(sys.argv[3]) else set()
s, _, m = v6.kernel_settings('poly')
n = 0
for p in f.by_type('IfcProduct'):
    if p.is_a() in v6.SKIP_TYPES or str(p.id()) in skip:
        continue
    items, _ = v6.body_items(p)
    if not items:
        continue
    print('BEGIN', p.id(), p.is_a(), p.GlobalId, repr(p.Name)[:60], flush=True)
    t = time.time()
    try:
        sh = ifcopenshell.geom.create_shape(s, p)
        nf = len(sh.geometry.faces) // 3
    except Exception as ex:
        nf = 'ERR ' + str(ex)[:80]
    dt = time.time() - t
    if dt > 2:
        print('SLOW', p.id(), round(dt, 1), nf, flush=True)
    n += 1
print('ALL DONE', n, flush=True)
