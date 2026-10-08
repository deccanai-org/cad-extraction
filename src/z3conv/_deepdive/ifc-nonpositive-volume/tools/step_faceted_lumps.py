#!/usr/bin/env python3
"""Text-level analysis of the FACETED_BREP solids an ifc2step writer produced (no OCC).
For each FACETED_BREP: faces, connected components (lumps, by shared CARTESIAN_POINT ids / rounded coords), signed volume
of every lump (divergence theorem over the POLY_LOOPs as written, FACE_BOUND orientation honoured), closedness
(every edge used exactly twice, once per direction), bbox, nesting of lumps (bbox containment).
usage: step_faceted_lumps.py FILE.step [--products NAME_RE] [--json OUT.jsonl] [--limit N]"""
import re, sys, json, argparse, collections
ap = argparse.ArgumentParser(); ap.add_argument('step'); ap.add_argument('--json'); ap.add_argument('--limit', type=int, default=0)
ap.add_argument('--only-multi', action='store_true')
a = ap.parse_args()
ent = {}
rx = re.compile(r'#(\d+)\s*=\s*([A-Z_0-9]*)\s*\((.*)\)\s*$', re.S)
buf = ''
with open(a.step, encoding='latin-1') as f:
    for line in f:
        buf += line
        if not buf.rstrip().endswith(';'):
            continue
        s, buf = buf.strip()[:-1], ''
        m = rx.match(s)
        if m:
            ent[int(m.group(1))] = (m.group(2), m.group(3))
refs = lambda s: [int(x) for x in re.findall(r'#(\d+)', s)]
pt = {}
for k, (t, b) in ent.items():
    if t == 'CARTESIAN_POINT':
        nums = re.findall(r'[-+0-9.Ee]+', b.split('(', 1)[1])
        pt[k] = tuple(float(x) for x in nums[:3])
def face_loops(fid):
    t, b = ent[fid]
    out = []
    for bid in refs(b.split(')', 1)[0]):
        bt, bb = ent[bid]
        lp = refs(bb)[0]; ori = '.T.' in bb.split(',')[-1]
        pids = refs(ent[lp][1])
        if not ori:
            pids = pids[::-1]
        out.append(pids)
    return out
def signed_vol(loops_list):
    v = 0.0
    for loops in loops_list:
        for pids in loops:
            p0 = pt[pids[0]]
            for i in range(1, len(pids) - 1):
                p1, p2 = pt[pids[i]], pt[pids[i + 1]]
                v += (p0[0] * (p1[1] * p2[2] - p1[2] * p2[1]) - p0[1] * (p1[0] * p2[2] - p1[2] * p2[0]) + p0[2] * (p1[0] * p2[1] - p1[1] * p2[0]))
    return v / 6.0
def key(p):
    return tuple(round(c, 2) for c in pt[p])
res = []; n = 0
stats = collections.Counter()
for k, (t, b) in ent.items():
    if t != 'FACETED_BREP':
        continue
    sh = refs(b)[0]; st, sb = ent[sh]
    fids = refs(sb)
    faces = [face_loops(f) for f in fids]
    # components by shared rounded point coordinates
    par = list(range(len(faces)))
    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    owner = {}
    for i, loops in enumerate(faces):
        for pids in loops:
            for p in pids:
                kk = key(p)
                if kk in owner:
                    ra, rb = find(i), find(owner[kk])
                    if ra != rb: par[ra] = rb
                else:
                    owner[kk] = i
    comps = collections.defaultdict(list)
    for i in range(len(faces)):
        comps[find(i)].append(i)
    lumps = []
    for c, idx in comps.items():
        ls = [faces[i] for i in idx]
        edges = collections.Counter()
        for loops in ls:
            for pids in loops:
                for i in range(len(pids)):
                    edges[(key(pids[i]), key(pids[(i + 1) % len(pids)]))] += 1
        bad_edges = sum(1 for (u, w), c_ in edges.items() if c_ != 1 or edges.get((w, u), 0) != 1)
        xs = [pt[p] for loops in ls for pids in loops for p in pids]
        bb = [min(x[0] for x in xs), min(x[1] for x in xs), min(x[2] for x in xs), max(x[0] for x in xs), max(x[1] for x in xs), max(x[2] for x in xs)]
        lumps.append({'faces': len(idx), 'vol': round(signed_vol(ls), 3), 'unmatched_edges': bad_edges, 'bbox': [round(x, 2) for x in bb]})
    # nesting: lump bbox inside another lump bbox
    for i, L in enumerate(lumps):
        L['inside_of'] = [j for j, M in enumerate(lumps) if j != i and all(M['bbox'][q] <= L['bbox'][q] + 1e-6 for q in range(3)) and all(M['bbox'][q + 3] >= L['bbox'][q + 3] - 1e-6 for q in range(3))]
    rec = {'brep': k, 'faces': len(fids), 'lumps': len(lumps), 'vol_total': round(sum(L['vol'] for L in lumps), 3), 'lump_detail': lumps}
    stats['breps'] += 1
    stats['multi_lump'] += len(lumps) > 1
    stats['neg_lump'] += any(L['vol'] <= 0 for L in lumps)
    stats['neg_total'] += rec['vol_total'] <= 0
    stats['nested_lumps'] += any(L['inside_of'] for L in lumps)
    stats['open_lump'] += any(L['unmatched_edges'] for L in lumps)
    res.append(rec)
    n += 1
    if a.limit and n >= a.limit:
        break
print(json.dumps(dict(stats)))
if a.json:
    with open(a.json, 'w') as g:
        for r in res:
            if a.only_multi and r['lumps'] < 2: continue
            g.write(json.dumps(r) + '\n')
