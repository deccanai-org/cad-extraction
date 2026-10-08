#!/usr/bin/env python3
"""bisect_mem.py CONV IFC [WORKERS=4] [TIMEOUT=120] [MEM_GB=6] - products whose kernel iteration (converter's polyhedral
settings, ifcopenshell iterator, 1 thread) exceeds MEM_GB or TIMEOUT: forked children per batch, failing batches halved"""
import sys, os, time, json, signal, resource, importlib.util
import numpy as np
import ifcopenshell, ifcopenshell.geom
spec = importlib.util.spec_from_file_location('v6', sys.argv[1])
v6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)
os.environ.setdefault('DEFLECTION', '0.005'); os.environ.setdefault('ANG_DEFLECTION', '0.6')
f = ifcopenshell.open(sys.argv[2])
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 4
TMO = float(sys.argv[4]) if len(sys.argv) > 4 else 120
MEM = float(sys.argv[5]) if len(sys.argv) > 5 else 6
ids = [p.id() for p in f.by_type('IfcProduct') if p.is_a() not in v6.SKIP_TYPES and v6.body_items(p)[0]]
t0 = time.time()
print('products', len(ids), file=sys.stderr, flush=True)
def child(batch):
    resource.setrlimit(resource.RLIMIT_AS, (int(MEM * 2 ** 30), int(MEM * 2 ** 30)))
    try:
        s, _, m = v6.kernel_settings('poly')
        it = ifcopenshell.geom.iterator(s, f, 1, include=[f.by_id(i) for i in batch])
        if it.initialize():
            while True:
                it.get()
                if not it.next():
                    break
    except MemoryError:
        os._exit(3)
    except Exception:
        pass
    os._exit(0)
def run(batches):
    pending = list(batches); running = {}; out = []
    while pending or running:
        while pending and len(running) < WORKERS:
            b = pending.pop()
            pid = os.fork()
            if pid == 0:
                child(b)
            running[pid] = (b, time.time())
        time.sleep(0.2)
        for pid, (b, st) in list(running.items()):
            r, status = os.waitpid(pid, os.WNOHANG)
            if r == pid:
                running.pop(pid); out.append((b, os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, status))
            elif time.time() - st > TMO * max(1, len(b) / 200):
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0); running.pop(pid); out.append((b, False, 'timeout'))
    return out
n = max(1, len(ids) // 32)
batches = [ids[i:i + n] for i in range(0, len(ids), n)]
culprits = []
while batches:
    res = run(batches)
    bad = [(b, st) for b, ok, st in res if not ok]
    print('round %d batches, %d failed (%.0fs)' % (len(batches), len(bad), time.time() - t0), file=sys.stderr, flush=True)
    batches = []
    for b, st in bad:
        if len(b) == 1:
            culprits.append((b[0], st))
        else:
            h = len(b) // 2; batches += [b[:h], b[h:]]
out = []
for i, st in culprits:
    e = f.by_id(i)
    items, _ = v6.body_items(e)
    out.append({'id': i, 'guid': e.GlobalId, 'type': e.is_a(), 'name': e.Name, 'status': str(st), 'items': [str(x)[:200] for x in items][:3],
                'openings': len(getattr(e, 'HasOpenings', None) or [])})
print(json.dumps({'products': len(ids), 'culprits': out, 'secs': round(time.time() - t0)}))
