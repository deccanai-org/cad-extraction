#!/usr/bin/env python3
"""Memory of ifc2step6's kernel pass: the products dev3 sends to the kernel (openings etc.) run through
kernel_run exactly as the converter calls it (ifcopenshell.geom.iterator, N threads, polyhedral), the consumer doing
the converter's own per-shape work (kernel_pieces + build_part). RSS is sampled every 2 s with the number of shapes
consumed; a watchdog stops the run at --limit-gb. --chunk K runs the same products through K-product iterators.
usage: probe_iter.py CONV.py IFC OUT.jsonl [--threads 4] [--limit-gb 40] [--chunk 0] [--max N] [--slow-consumer SEC]"""
import sys, os, json, time, threading, argparse, importlib.util
ap = argparse.ArgumentParser()
ap.add_argument('conv'); ap.add_argument('ifc'); ap.add_argument('out')
ap.add_argument('--threads', type=int, default=4); ap.add_argument('--limit-gb', type=float, default=40)
ap.add_argument('--chunk', type=int, default=0); ap.add_argument('--max', type=int, default=0)
ap.add_argument('--no-build', action='store_true')
a = ap.parse_args()
spec = importlib.util.spec_from_file_location('conv', a.conv); M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
import ifcopenshell, ifcopenshell.geom
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
out = open(a.out, 'w')
ST = {'consumed': 0, 'phase': 'open', 't0': time.time()}


def rss_mb():
    for line in open('/proc/self/status'):
        if line.startswith('VmRSS:'):
            return int(line.split()[1]) >> 10
    return -1


def watch():
    while True:
        time.sleep(2)
        r = rss_mb()
        out.write(json.dumps({'t': round(time.time() - ST['t0'], 1), 'rss_mb': r, 'consumed': ST['consumed'], 'phase': ST['phase']}) + '\n'); out.flush()
        if r > a.limit_gb * 1024:
            out.write(json.dumps({'KILLED': True, 'rss_mb': r, 'consumed': ST['consumed']}) + '\n'); out.flush()
            os._exit(137)


threading.Thread(target=watch, daemon=True).start()
f = ifcopenshell.open(a.ifc)
prods = []
for p in f.by_type('IfcProduct'):
    if p.is_a() in M.SKIP_TYPES:
        continue
    items, _ = M.body_items(p)
    if items and (getattr(p, 'HasOpenings', None) or []):
        prods.append(p)
if a.max:
    prods = prods[:a.max]
ST['phase'] = 'kernel %d products' % len(prods)
rep = M.Repair(2)
stats = {}


def on_shape(eid, V, faces, iids):
    ST['consumed'] += 1
    if not a.no_build:
        M.build_part(M.kernel_pieces(f, V, faces, iids), rep)


t = time.time()
if a.chunk:
    for i in range(0, len(prods), a.chunk):
        M.kernel_run(f, prods[i:i + a.chunk], a.threads, 'poly', 'k%d' % i, stats, on_shape)
else:
    M.kernel_run(f, prods, a.threads, 'poly', 'k', stats, on_shape)
out.write(json.dumps({'done': True, 'sec': round(time.time() - t, 1), 'consumed': ST['consumed'], 'rss_mb': rss_mb(), 'products': len(prods)}) + '\n'); out.flush()
