"""Find the STEP roots whose OCC transfer segfaults: read once, fork children that transfer batches of roots,
split crashing batches.  usage: rootbisect.py FILE.step [WORKERS]"""
import os, sys, time, json
from OCC.Core.STEPControl import STEPControl_Reader
path = sys.argv[1]; W = int(sys.argv[2]) if len(sys.argv) > 2 else 8
t0 = time.time(); r = STEPControl_Reader(); r.ReadFile(path); n = r.NbRootsForTransfer()
print(f'read {time.time()-t0:.0f}s roots {n}', file=sys.stderr, flush=True)
def child(ids):
    for i in ids:
        r.TransferRoot(i)
    os._exit(0)
def run(batches):
    pend = list(batches); running = {}; out = []
    while pend or running:
        while pend and len(running) < W:
            ids = pend.pop(); pid = os.fork()
            if pid == 0: child(ids)
            running[pid] = ids
        pid, st = os.wait()
        ids = running.pop(pid); out.append((ids, os.WIFEXITED(st) and os.WEXITSTATUS(st) == 0))
    return out
k = max(1, n // 64); batches = [list(range(i, min(n + 1, i + k))) for i in range(1, n + 1, k)]
bad = []
while batches:
    res = run(batches); batches = []
    for ids, ok in res:
        if ok: continue
        if len(ids) == 1: bad.append(ids[0])
        else: h = len(ids) // 2; batches += [ids[:h], ids[h:]]
    print(f'round {time.time()-t0:.0f}s next {len(batches)} bad {len(bad)}', file=sys.stderr, flush=True)
out = []
for i in bad:
    e = r.RootForTransfer(i)
    out.append({'root': i, 'type': e.DynamicType().Name(), 'id': r.Model().Number(e)})
print(json.dumps({'roots': n, 'crashing': out, 'sec': round(time.time() - t0)}))
