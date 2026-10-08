#!/usr/bin/env python3
"""Edge-connectivity lump analysis of every FACETED_BREP in an ifc2step STEP (pure text, no OCC).
Faces are connected when they share an edge (same unordered CARTESIAN_POINT id pair), which is what OpenCASCADE's
StepToTopoDS builds (edges are shared by vertex pair). Per lump: faces, signed volume (divergence theorem), closed
(each undirected edge used exactly twice, in opposite directions), bbox.
Output per FACETED_BREP keyed by the PRODUCT_DEFINITION entity id of its root (= step_check root label).
usage: step_lumps2.py FILE.step OUT.jsonl"""
import re, sys, json, collections
src, dst = sys.argv[1], sys.argv[2]
ent = {}
rx = re.compile(r'#(\d+)\s*=\s*([A-Z_0-9]*)\s*\((.*)\)\s*$', re.S)
buf = ''
with open(src, encoding='latin-1') as f:
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
# rep -> pd
pds_pd = {k: refs(b)[0] for k, (t, b) in ent.items() if t == 'PRODUCT_DEFINITION_SHAPE'}
rep_pd = {}; pd_name = {}
for k, (t, b) in ent.items():
    if t == 'SHAPE_DEFINITION_REPRESENTATION':
        r_ = refs(b); rep_pd[r_[1]] = pds_pd.get(r_[0])
brep_pd = {}
for k, (t, b) in ent.items():
    if t.endswith('SHAPE_REPRESENTATION') and k in rep_pd:
        nm = re.match(r"\s*'((?:[^']|'')*)'", b); nm = nm.group(1) if nm else ''
        for x in refs(b.rsplit(',', 1)[0]):
            if ent.get(x, ('',))[0] == 'FACETED_BREP':
                brep_pd[x] = (rep_pd[k], nm)
def face_loops(fid):
    t, b = ent[fid]
    out = []
    for bid in refs(b.split(')', 1)[0]):
        bt, bb = ent[bid]
        lp = refs(bb)[0]; ori = '.T.' in bb.rsplit(',', 1)[-1]
        pids = refs(ent[lp][1])
        if not ori:
            pids = pids[::-1]
        out.append(pids)
    return out
def svol(loops_list):
    v = 0.0
    for loops in loops_list:
        for pids in loops:
            p0 = pt[pids[0]]
            for i in range(1, len(pids) - 1):
                p1, p2 = pt[pids[i]], pt[pids[i + 1]]
                v += (p0[0] * (p1[1] * p2[2] - p1[2] * p2[1]) - p0[1] * (p1[0] * p2[2] - p1[2] * p2[0]) + p0[2] * (p1[0] * p2[1] - p1[1] * p2[0]))
    return v / 6.0
fo = open(dst, 'w'); st = collections.Counter()
for k, (t, b) in ent.items():
    if t != 'FACETED_BREP':
        continue
    faces = [face_loops(f) for f in refs(ent[refs(b)[0]][1])]
    par = list(range(len(faces)))
    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    eo = {}
    for i, loops in enumerate(faces):
        for pids in loops:
            for j in range(len(pids)):
                e = frozenset((pids[j], pids[(j + 1) % len(pids)]))
                if e in eo:
                    ra, rb = find(i), find(eo[e])
                    if ra != rb: par[ra] = rb
                else:
                    eo[e] = i
    comps = collections.defaultdict(list)
    for i in range(len(faces)):
        comps[find(i)].append(i)
    lumps = []
    for idx in comps.values():
        de = collections.Counter()
        for i in idx:
            for pids in faces[i]:
                for j in range(len(pids)):
                    de[(pids[j], pids[(j + 1) % len(pids)])] += 1
        bad = sum(1 for (u, w), c in de.items() if c != 1 or de.get((w, u), 0) != 1)
        xs = [pt[p] for i in idx for pids in faces[i] for p in pids]
        bb = [round(min(x[q] for x in xs), 2) for q in range(3)] + [round(max(x[q] for x in xs), 2) for q in range(3)]
        lumps.append({'faces': len(idx), 'vol': round(svol([faces[i] for i in idx]), 3), 'bad_edges': bad, 'bbox': bb})
    pd, nm = brep_pd.get(k, (None, None))
    closed_all = all(L['bad_edges'] == 0 for L in lumps)
    kind = ('single_closed' if len(lumps) == 1 and closed_all else 'multi_closed' if closed_all else
            'single_open' if len(lumps) == 1 else 'multi_with_open')
    st[kind] += 1
    st['neg_lumps'] += sum(1 for L in lumps if L['vol'] <= 0)
    fo.write(json.dumps({'brep': k, 'pd': pd, 'name': nm, 'faces': len(faces), 'lumps': len(lumps), 'kind': kind,
                         'neg_lumps': sum(1 for L in lumps if L['vol'] <= 0), 'lump_detail': lumps}) + '\n')
print(json.dumps(dict(st)))
