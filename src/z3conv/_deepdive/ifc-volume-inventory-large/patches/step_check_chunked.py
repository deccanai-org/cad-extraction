#!/usr/bin/env python3
"""OpenCASCADE read-back of a STEP file too large to read in one piece (> RB_MAX), with bounded memory.
usage: step_check_chunked.py FILE.step OUT.json [--parts OUT.parts.jsonl.gz] [--chunk-mb 150] [--jobs 1]
                             [--check step_check.py] [--py PYTHON] [--workdir DIR] [--max-check N]

1. index pass (mmap + one regex scan): byte offset of every entity '#id=' that starts a line, the header, and the
   cut points = ends of SHAPE_DEFINITION_REPRESENTATION lines (a product block is complete there in ifc2step5 output;
   other writers: any entity boundary works, see 2)
2. chunks of ~chunk-mb ending at a cut point; each chunk is written as a self-contained STEP: header + the transitive
   closure of every entity it references outside its own byte range (contexts, units, shared DIRECTIONs, ...; any
   reference is resolved through the offset index, so the split is valid for every writer) + its own entities
3. step_check.py (same checks as a normal read-back: per root solids / BRepCheck / volume / bbox) on each chunk,
   sequentially or --jobs in parallel; per-part rows are merged (deduplicated by product id+name), totals summed,
   bbox united; markers / products come from a text pass over the whole file (step_check --no-occ)
Assemblies (NEXT_ASSEMBLY_USAGE_OCCURRENCE) are refused (roots would be split / double counted): text-only then.
Output = step_check JSON + {'chunked': {...}}; no render (render_ink None, 'render_skipped': 'chunked read-back')."""
import sys, os, re, json, mmap, array, gzip, time, argparse, subprocess, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument('step'); ap.add_argument('out'); ap.add_argument('--parts')
ap.add_argument('--chunk-mb', type=int, default=150); ap.add_argument('--jobs', type=int, default=1)
ap.add_argument('--check', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'step_check.py'))
ap.add_argument('--py', default=sys.executable); ap.add_argument('--workdir')
ap.add_argument('--max-check', type=int, default=150000); ap.add_argument('--timeout', type=int, default=4 * 3600)
ap.add_argument('--retries', type=int, default=1)   # a chunk killed / failed (e.g. memory pressure with --jobs > 1) is re-run alone
a = ap.parse_args()
T0 = time.time()
wd = a.workdir or tempfile.mkdtemp(prefix='scc_', dir=os.path.dirname(os.path.abspath(a.out)))
os.makedirs(wd, exist_ok=True)

# ------------------------------------------------------------------ 0. whole-file text pass (markers, products)
txt = os.path.join(wd, 'text.json')
subprocess.run([a.py, a.check, a.step, txt, '--no-occ'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=a.timeout)
try:
    out = json.load(open(txt))
except Exception:
    out = {'file': os.path.basename(a.step), 'bytes': os.path.getsize(a.step), 'skipped': 'text pass failed'}
    json.dump(out, open(a.out, 'w')); print(json.dumps(out)); sys.exit(0)
if out.get('markers', {}).get('NEXT_ASSEMBLY_USAGE_OCCURRENCE'):
    out['skipped'] = 'chunked read-back refused: STEP assembly structure (NAUO); text checks only'
    json.dump(out, open(a.out, 'w')); print(json.dumps(out)); sys.exit(0)

# ------------------------------------------------------------------ 1. index pass
fh = open(a.step, 'rb')
mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
size = len(mm)
m = re.search(rb'(?m)^DATA;\s*$', mm)
if not m:
    out['skipped'] = 'chunked read-back: no DATA section'; json.dump(out, open(a.out, 'w')); sys.exit(0)
header = mm[:m.end()] + b'\n'
data0 = m.end()
endsec = mm.rfind(b'ENDSEC;')
pos = array.array('q')                       # id -> byte offset (-1 = unknown); dense ids in practice
ENT = re.compile(rb'(?m)^#(\d+)\s*=\s*([A-Z_0-9]*)')
cuts = []                                    # byte offsets just after a SHAPE_DEFINITION_REPRESENTATION entity
prev_sdr = False
n_ent = 0
for e in ENT.finditer(mm, data0, endsec if endsec > 0 else size):
    i = int(e.group(1)); o = e.start()
    if prev_sdr:
        cuts.append(o)
    prev_sdr = e.group(2) == b'SHAPE_DEFINITION_REPRESENTATION'
    if i >= len(pos):
        pos.extend([-1] * (i + 1 - len(pos) + (1 << 16)))
    pos[i] = o
    n_ent += 1
data1 = endsec if endsec > 0 else size
idx_sec = round(time.time() - T0, 1)
NEXT = re.compile(rb'(?m)^#\d+\s*=|^ENDSEC;')


def ent_text(i):
    o = pos[i] if 0 <= i < len(pos) else -1
    if o < 0:
        return None
    n = NEXT.search(mm, o + 1)
    return mm[o:n.start() if n else data1]


REF = re.compile(rb'#(\d+)')

# chunk boundaries (byte ranges) at cut points
target = a.chunk_mb << 20
bounds = []; start = data0; ci = 0
while start < data1:
    want = start + target
    if want >= data1:
        bounds.append((start, data1)); break
    while ci < len(cuts) and cuts[ci] < want:
        ci += 1
    end = cuts[ci] if ci < len(cuts) else data1
    if end - start > 3 * target:                     # no cut point near: split at any entity boundary
        n = NEXT.search(mm, want)
        end = n.start() if n else data1
    bounds.append((start, end)); start = end


def build(k, b0, b1):
    """write chunk k as a self-contained STEP; returns (path, closure size)"""
    body = mm[b0:b1]
    need = set(); seen = set()
    for r in REF.finditer(body):
        i = int(r.group(1))
        if i in seen:
            continue
        seen.add(i)
        o = pos[i] if i < len(pos) else -1
        if o >= 0 and not (b0 <= o < b1):
            need.add(i)
    del seen
    clos = {}; todo = list(need)
    while todo:
        i = todo.pop()
        if i in clos:
            continue
        t = ent_text(i)
        if t is None:
            continue
        clos[i] = t
        for r in REF.finditer(t):
            j = int(r.group(1))
            o = pos[j] if j < len(pos) else -1
            if o >= 0 and not (b0 <= o < b1) and j not in clos:
                todo.append(j)
    p = os.path.join(wd, 'chunk_%04d.step' % k)
    with open(p, 'wb') as g:
        g.write(header)
        for i in sorted(clos):
            t = clos[i]
            g.write(t if t.endswith(b'\n') else t + b'\n')
        g.write(body)
        g.write(b'ENDSEC;\nEND-ISO-10303-21;\n')
    return p, len(clos)


def run(k):
    b0, b1 = bounds[k]
    p, nclos = build(k, b0, b1)
    oj = p + '.json'; op = p + '.parts.jsonl.gz'
    t = time.time()
    try:
        rc = subprocess.run([a.py, a.check, p, oj, '--parts', op, '--max-check', str(a.max_check)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=a.timeout).returncode
    except subprocess.TimeoutExpired:
        rc = 124
    try:
        r = json.load(open(oj))
    except Exception:
        r = {'read_status': f'fail:rc{rc}'}
    parts = []
    if os.path.exists(op):
        with gzip.open(op, 'rt') as g:
            parts = [json.loads(l) for l in g if l.strip()]
    for f_ in (p, oj, op):
        if os.path.exists(f_):
            os.remove(f_)
    return k, rc, r, parts, nclos, round(time.time() - t, 1), b1 - b0


SUM = ('roots', 'transferred', 'empty_roots', 'solids', 'shells', 'faces', 'checked', 'valid', 'invalid', 'nonpos_vol',
       'nonfinite', 'roots_mapped_to_products')
tot = dict.fromkeys(SUM, 0); bb = None; inv = []; parts_all = []; seen_in = {}; dup_roots = 0; chunks = []; fails = []; sampled = False; cf = 1.0
def results():
    """chunk results in parallel; failed chunks re-run one at a time (memory pressure / transient kills)"""
    res = {}
    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        for t in ex.map(run, range(len(bounds))):
            res[t[0]] = t
    for _ in range(max(0, a.retries)):
        for k in sorted(k for k, t in res.items() if t[2].get('read_status') != 'ok'):
            t = run(k)
            t[2]['retried'] = True
            res[k] = t
    return [res[k] for k in sorted(res)]


for k, rc, r, parts, nclos, sec, nb in results():
    chunks.append({'k': k, 'mb': round(nb / 1048576, 1), 'closure': nclos, 'rc': rc, 'sec': sec, 'roots': r.get('roots'),
                   'read': r.get('read_status'), 'retried': r.get('retried', False)})
    if r.get('read_status') != 'ok':
        fails.append(k); continue
    for x in SUM:
        tot[x] += r.get(x) or 0
    sampled = sampled or bool(r.get('sampled')); cf = min(cf, r.get('check_fraction') or 1.0)
    if r.get('bbox'):
        b = r['bbox']
        bb = b if bb is None else [min(bb[0], b[0]), min(bb[1], b[1]), min(bb[2], b[2]), max(bb[3], b[3]), max(bb[4], b[4]), max(bb[5], b[5])]
    inv += r.get('invalid_examples') or []
    for p in parts:
        # roots never repeat across chunks when cuts follow SDR lines; with arbitrary cuts a root pulled in through a
        # closure could: drop exact repeats (same product, faces, volume, bbox) seen in an EARLIER chunk only
        key = (p.get('pid'), p.get('name'), p.get('faces'), p.get('volume'), tuple(p.get('bbox') or ()))
        if seen_in.setdefault(key, k) != k:
            dup_roots += 1; continue
        p['chunk'] = k
        parts_all.append(p)
mm.close(); fh.close()
out.update(tot)
out['read_status'] = 'ok' if not fails else f'fail:chunks {fails[:10]}'
out['bbox'] = [round(v, 3) for v in bb] if bb else None
out['invalid_examples'] = inv[:50]
out['sampled'] = sampled; out['check_fraction'] = cf
if tot['checked']:
    f_ = tot['solids'] / tot['checked']
    out['valid_solids_est'] = int(round(tot['valid'] * f_)); out['invalid_solids_est'] = int(round(tot['invalid'] * f_))
    out['invalid_frac'] = round(tot['invalid'] / tot['checked'], 6)
out['render_ink'] = None; out['render_skipped'] = 'chunked read-back (no single scene)'
out['chunked'] = {'chunks': len(bounds), 'chunk_mb': a.chunk_mb, 'entities': n_ent, 'index_sec': idx_sec, 'failed_chunks': fails, 'duplicate_roots_dropped': dup_roots,
                  'closure_max': max((c['closure'] for c in chunks), default=0), 'per_chunk': sorted(chunks, key=lambda c: c['k'])[:400]}
if a.parts:
    rows = sorted(parts_all, key=lambda p: (p.get('chunk', 0), p.get('i', 0)))
    with gzip.open(a.parts, 'wt') as g:
        for n, p in enumerate(rows, 1):
            p['i'] = n
            g.write(json.dumps(p) + '\n')
    out['parts_rows'] = len(rows)
out['sec'] = round(time.time() - T0, 1)
if not a.workdir:
    shutil.rmtree(wd, ignore_errors=True)
json.dump(out, open(a.out, 'w'))
print(json.dumps({k: v for k, v in out.items() if k != 'chunked'}))
