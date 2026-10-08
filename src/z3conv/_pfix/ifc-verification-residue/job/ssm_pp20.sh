#!/bin/bash
S=/work/agentwork/ifc-verification-residue/w/ppv_vr4b/2c0f7a89ddf2d595/out.step
ls -la $S
/opt/conv/env/bin/python - $S <<'PY'
import sys, re, gzip, json
S = sys.argv[1]
want_names = {'pp20'}
ents = {}
# pass 1: index PRODUCT lines named pp20 and all MAPPED_ITEM / AXIS2 / DIRECTION / CARTESIAN_POINT / SHAPE_REPRESENTATION lines near them
prod = {}
lines = {}
rx = re.compile(r"^#(\d+)=([A-Z_0-9]+)\((.*)\);$")
need_types = ('PRODUCT', 'PRODUCT_DEFINITION_FORMATION', 'PRODUCT_DEFINITION', 'PRODUCT_DEFINITION_SHAPE', 'SHAPE_DEFINITION_REPRESENTATION', 'SHAPE_REPRESENTATION', 'MAPPED_ITEM', 'AXIS2_PLACEMENT_3D', 'DIRECTION', 'CARTESIAN_POINT')
for line in open(S, encoding='latin-1'):
    m = rx.match(line.strip())
    if not m or m.group(2) not in need_types:
        continue
    if m.group(2) == 'CARTESIAN_POINT' or m.group(2) == 'DIRECTION':
        lines[int(m.group(1))] = (m.group(2), m.group(3))
        continue
    lines[int(m.group(1))] = (m.group(2), m.group(3))
refs = lambda b: [int(x) for x in re.findall(r'#(\d+)', b)]
pids = {k for k, (t, b) in lines.items() if t == 'PRODUCT' and "'pp20'" in b}
pdf = {k: refs(b)[-1] for k, (t, b) in lines.items() if t == 'PRODUCT_DEFINITION_FORMATION' and refs(b)[-1] in pids}
pd = {k: refs(b)[0] for k, (t, b) in lines.items() if t == 'PRODUCT_DEFINITION' and refs(b)[0] in pdf}
pds = {k: refs(b)[0] for k, (t, b) in lines.items() if t == 'PRODUCT_DEFINITION_SHAPE' and refs(b)[0] in pd}
for k, (t, b) in lines.items():
    if t != 'SHAPE_DEFINITION_REPRESENTATION':
        continue
    r = refs(b)
    if r[0] not in pds:
        continue
    prod_id = pdf[pd[pds[r[0]]]]
    gid = re.findall(r"'([^']*)'", lines[prod_id][1])[0]
    sr = lines[r[1]]
    mi = [x for x in refs(sr[1]) if lines.get(x, ('',))[0] == 'MAPPED_ITEM'][0]
    ax = refs(lines[mi][1])[1]
    p, z, x = refs(lines[ax][1])
    print(gid, 'map', refs(lines[mi][1])[0], 'loc', lines[p][1], 'z', lines[z][1], 'x', lines[x][1])
PY
