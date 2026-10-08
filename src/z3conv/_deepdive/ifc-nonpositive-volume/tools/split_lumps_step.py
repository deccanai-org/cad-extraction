#!/usr/bin/env python3
"""STEP->STEP repair for ifc2step faceted output (no OCC): every FACETED_BREP whose CLOSED_SHELL holds more than one
edge-connected lump is split into one CLOSED_SHELL + FACETED_BREP per lump, and the shape representation lists them
all (ISO 10303-42: a closed_shell is a connected_face_set, so one lump per shell); internal coincident face pairs
are dropped where that leaves closed shells (see patch/lumpsplit.py for the exact rules).
Streaming, entity ids of new entities are appended after the current max id; everything else is copied verbatim.
usage: split_lumps_step.py IN.step OUT.step"""
import re, sys, os, json, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'patch'))
import lumpsplit
src, dst = sys.argv[1], sys.argv[2]
rx = re.compile(r'#(\d+)\s*=\s*([A-Z_0-9]*)\s*\((.*)\)\s*$', re.S)
ent = {}; order = []
head, tail = [], []
buf = ''; in_data = False; done = False
with open(src, encoding='latin-1') as f:
    for line in f:
        if not in_data:
            head.append(line)
            if line.strip() == 'DATA;':
                in_data = True
            continue
        if done:
            tail.append(line); continue
        if not buf and line.strip().startswith('ENDSEC'):
            done = True; tail.append(line); continue
        buf += line
        if not buf.rstrip().endswith(';'):
            continue
        s, buf = buf.strip()[:-1], ''
        m = rx.match(s)
        if m:
            k = int(m.group(1)); ent[k] = (m.group(2), m.group(3)); order.append(k)
refs = lambda s: [int(x) for x in re.findall(r'#(\d+)', s)]
pt = {}
for k, (t, b) in ent.items():
    if t == 'CARTESIAN_POINT':
        pt[k] = tuple(float(x) for x in re.findall(r'[-+0-9.Ee]+', b.split('(', 1)[1])[:3])
def face_loops(fid):
    out = []
    for bid in refs(ent[fid][1].split(')', 1)[0]):
        bb = ent[bid][1]
        pids = refs(ent[refs(bb)[0]][1])
        out.append(pids if '.T.' in bb.rsplit(',', 1)[-1] else pids[::-1])
    return out
def svol(fl):
    v = 0.0
    for loops in fl:
        for p in loops:
            a = pt[p[0]]
            for i in range(1, len(p) - 1):
                b, c = pt[p[i]], pt[p[i + 1]]
                v += a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
    return v / 6.0
nid = max(ent) + 1; new = []; repl = {}; drop = set(); st = collections.Counter()
def add(body):
    global nid
    i = nid; nid += 1; new.append('#%d=%s;\n' % (i, body)); return i
for k in order:
    t, b = ent[k]
    if t != 'FACETED_BREP':
        continue
    shell = refs(b)[0]
    fids = refs(ent[shell][1])
    loops = [face_loops(f) for f in fids]
    comps, info = lumpsplit.decompose(loops, pt)
    st['breps'] += 1
    for kk in ('cancelled_faces', 'nonmanifold_edges', 'radial_edges', 'kept_whole', 'cancel_rejected', 'voids_kept'):
        st[kk] += info.get(kk, 0)
    if len(comps) < 2 and not info['cancelled_faces']:
        continue
    st['breps_split'] += len(comps) > 1
    out = []
    for c in comps:
        sh = add("CLOSED_SHELL('',(%s))" % ','.join('#%d' % fids[i] for i in c['faces']))
        out.append(add("FACETED_BREP('',#%d)" % sh))
        st['lumps_written'] += 1
    repl[k] = out
    drop.add(k); drop.add(shell)
# representation items: replace the brep id by the per-lump breps
with open(dst, 'w', encoding='latin-1') as g:
    g.writelines(head)
    for k in order:
        if k in drop:
            continue                      # the split FACETED_BREP and its multi-lump CLOSED_SHELL (now unreferenced)
        t, b = ent[k]
        if t.endswith('SHAPE_REPRESENTATION') and repl:
            m = re.match(r"(\s*'(?:[^']|'')*'\s*,\s*\()(.*?)(\)\s*,\s*#\d+\s*)$", b, re.S)
            if m and any(int(x) in repl for x in re.findall(r'#(\d+)', m.group(2))):
                its = []
                for x in re.findall(r'#(\d+)', m.group(2)):
                    its += ['#%d' % y for y in repl.get(int(x), [int(x)])]
                b = m.group(1) + ','.join(its) + m.group(3)
        g.write('#%d=%s(%s);\n' % (k, t, b))
    g.writelines(new)
    g.writelines(tail)
print(json.dumps(dict(st)))
