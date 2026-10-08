#!/usr/bin/env python3
"""Do members that v5.x counts as 'without geometry' carry material placements the converter does not link?
Per member type: member files with orthonormal frames, with material instances (piece ids in the piece table),
with bolt records. usage: misc_probe.py PIPE JOB OUT_JSON"""
import sys, os, json, collections
import numpy as np
PIPE, job, out = sys.argv[1:4]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import sds2job, instances, piece_table, bolts
pieces = piece_table.read_pieces(job)
mems, _ = sds2job.read_members(job)
st = collections.defaultdict(collections.Counter)
ex = collections.defaultdict(list)
for m in mems:
    t = m.type
    s = st[t]
    s['members'] += 1
    try:
        main_sid, inst = instances.material_instances(job, m.id, pieces)
    except Exception:
        inst = []; s['instances_error'] += 1
    if inst:
        s['with_material_instances'] += 1; s['material_instances'] += len(inst)
    try:
        fr = instances.count_frames(job, m.id)
    except Exception:
        fr = 0
    if fr:
        s['with_frames'] += 1; s['frames'] += fr
    if not inst and fr:
        s['frames_but_no_instances'] += 1
        if len(ex[t]) < 5:
            ex[t].append({'member': m.id, 'frames': fr, 'bytes': os.path.getsize(os.path.join(job, 'mem', str(m.id)))})
    try:
        b = bolts.member_bolts(job, m.id)
    except Exception:
        b = []
    if b:
        s['with_bolt_records'] += 1
    if m.section is None:
        s['no_section'] += 1
res = {'pieces_in_table': len(pieces), 'by_type': {k: dict(v) for k, v in st.items()}, 'examples': ex}
json.dump(res, open(out, 'w'), indent=1)
print(json.dumps(res)[:3000])
