#!/usr/bin/env python3
"""Which product makes the kernel pass blow up (memory / time)? Products that ifc2step6 dev3 sends to the kernel
(openings, unsupported items, ...) are meshed ONE BY ONE (create_shape, polyhedral like the converter) in this process;
per product: seconds, RSS after, faces. A watchdog thread ends the process when RSS exceeds the limit and names the
product being meshed.
usage: probe_kernel.py CONV.py IFC OUT.jsonl [--limit-gb 40] [--only-openings] [--start N] [--max-sec-log 2]"""
import sys, os, json, time, threading, argparse, importlib.util
ap = argparse.ArgumentParser()
ap.add_argument('conv'); ap.add_argument('ifc'); ap.add_argument('out')
ap.add_argument('--limit-gb', type=float, default=40); ap.add_argument('--only-openings', action='store_true')
ap.add_argument('--start', type=int, default=0); ap.add_argument('--end', type=int, default=0); ap.add_argument('--ids', default=None)
a = ap.parse_args()
spec = importlib.util.spec_from_file_location('conv', a.conv); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
import ifcopenshell, ifcopenshell.geom
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
CUR = {'id': None, 't': time.time()}
out = open(a.out, 'a')


def rss_mb():
    for line in open('/proc/self/status'):
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) >> 10
    return -1


def watch():
    lim = a.limit_gb * 1024
    peak = 0
    while True:
        time.sleep(0.5)
        r = rss_mb(); peak = max(peak, r)
        if r > lim:
            out.write(json.dumps({'KILLED_AT': CUR['id'], 'rss_mb': r, 'sec_in_product': round(time.time() - CUR['t'], 1)}) + '\n'); out.flush()
            os._exit(137)


threading.Thread(target=watch, daemon=True).start()
t0 = time.time()
f = ifcopenshell.open(a.ifc)
out.write(json.dumps({'open_sec': round(time.time() - t0, 1), 'rss_mb': rss_mb()}) + '\n'); out.flush()
prods = [p for p in f.by_type('IfcProduct') if p.is_a() not in M.SKIP_TYPES]
sel = []
for p in prods:
    items, _ = M.body_items(p)
    if not items:
        continue
    op = getattr(p, 'HasOpenings', None) or []
    if a.only_openings and not op:
        continue
    sel.append(p)
if a.ids:
    want = set(a.ids.split(','))
    sel = [p for p in sel if p.GlobalId in want or str(p.id()) in want]
out.write(json.dumps({'selected': len(sel), 'start': a.start}) + '\n'); out.flush()
s, _, m = M.kernel_settings('poly')
for k, p in enumerate(sel[a.start:(a.end or len(sel))], a.start):
    CUR['id'] = [k, p.id(), p.GlobalId, p.is_a(), p.Name]; CUR['t'] = time.time()
    if os.environ.get('PROBE_VERBOSE'):
        out.write(json.dumps({'start': k, 'eid': p.id(), 'gid': p.GlobalId, 'name': p.Name, 'openings': len(getattr(p, 'HasOpenings', None) or [])}) + '\n'); out.flush()
    r0 = rss_mb(); t1 = time.time()
    rec = {'k': k, 'eid': p.id(), 'gid': p.GlobalId, 'cls': p.is_a(), 'name': p.Name, 'openings': len(getattr(p, 'HasOpenings', None) or [])}
    try:
        sh = ifcopenshell.geom.create_shape(s, p)
        V, faces, iids = M.kernel_geometry(sh.geometry, m)
        rec.update(faces=len(faces), verts=len(V))
    except Exception as e:
        rec['err'] = str(e)[:120]
    rec.update(sec=round(time.time() - t1, 2), rss_mb=rss_mb(), d_rss=rss_mb() - r0)
    if rec['sec'] > 1 or rec['d_rss'] > 200 or k % 500 == 0 or 'err' in rec:
        out.write(json.dumps(rec) + '\n'); out.flush()
out.write(json.dumps({'done': True, 'sec': round(time.time() - t0, 1), 'rss_mb': rss_mb()}) + '\n'); out.flush()
