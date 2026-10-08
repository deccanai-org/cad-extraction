"""Find the elements on which the geometry kernel crashes (segfault) or hangs, for one IFC.
Parses once, computes the set the converter would tessellate (ifc2step5 run_transcode's skipped list),
then forks children that mesh batches of those products with create_shape; a batch whose child dies or
times out is split in halves until single culprits remain.
  ifc_crash_bisect.py FILE.ifc IFC2STEP5_PY [WORKERS=4] [TIMEOUT_S=300]  -> prints JSON {culprits:[guid...]}"""
import importlib.util, json, os, signal, sys, time
import ifcopenshell, ifcopenshell.geom

path, conv = sys.argv[1], sys.argv[2]
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 4
TMO = float(sys.argv[4]) if len(sys.argv) > 4 else 300
spec = importlib.util.spec_from_file_location("ifc2step5", conv); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
t0 = time.time()
f = ifcopenshell.open(path)
w = m.StepWriter(open(os.devnull, "w"), "x", ".MILLI.", 0.01)
try: w.sc = float(ifcopenshell.util.unit.calculate_unit_scale(f)) * 1000.0
except Exception: w.sc = 1000.0
stats = {}
skipped = m.run_transcode(f, w, stats)
print(f"parsed+transcode {time.time()-t0:.0f}s; tessellate set {len(skipped)}", file=sys.stderr, flush=True)
settings = ifcopenshell.geom.settings(); settings.set("use-world-coords", True)

def child(ids):
    for i in ids:
        try: ifcopenshell.geom.create_shape(settings, f.by_id(i))
        except Exception: pass          # python-level failures are not crashes
    os._exit(0)

def run(batches):
    """batches: list of id lists -> list of (ids, ok)"""
    pending = list(batches); running = {}; out = []
    while pending or running:
        while pending and len(running) < WORKERS:
            ids = pending.pop()
            pid = os.fork()
            if pid == 0: child(ids)
            running[pid] = (ids, time.time())
        time.sleep(0.2)
        for pid, (ids, st) in list(running.items()):
            r, status = os.waitpid(pid, os.WNOHANG)
            if r == pid:
                running.pop(pid); out.append((ids, os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0))
            elif time.time() - st > TMO * max(1, len(ids) / 50):
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0); running.pop(pid); out.append((ids, False))
    return out

n = max(1, len(skipped) // 64)
batches = [skipped[i:i + n] for i in range(0, len(skipped), n)]
culprits = []
while batches:
    res = run(batches)
    bad = [ids for ids, ok in res if not ok]
    print(f"round: {len(batches)} batches, {len(bad)} crashed ({time.time()-t0:.0f}s)", file=sys.stderr, flush=True)
    batches = []
    for ids in bad:
        if len(ids) == 1: culprits.append(ids[0])
        else: h = len(ids) // 2; batches += [ids[:h], ids[h:]]
out = []
for i in culprits:
    e = f.by_id(i)
    out.append({"id": i, "guid": getattr(e, "GlobalId", None), "type": e.is_a(), "name": getattr(e, "Name", None)})
print(json.dumps({"file": os.path.basename(path), "tessellate_set": len(skipped), "culprits": out, "secs": round(time.time() - t0)}))
