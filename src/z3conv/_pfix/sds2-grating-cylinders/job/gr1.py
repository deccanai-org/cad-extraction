#!/usr/bin/env python3
"""gr1.py PIPE JOB OUT.json : where does an SDS2 job keep grating data? strings in setup files, piece-table slots of
grating pieces vs plates, grating piece-file layout, owning member blocks."""
import sys, os, re, json, struct, collections
import numpy as np
PIPE, job, outp = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
from piece_table import read_pieces, slot_size, LAYOUTS
from instances import material_instances
from sds2job import read_members
import brep
res = dict(job=job)
# 1. job tree
tree = collections.Counter()
for root, dirs, files in os.walk(job):
    rel = os.path.relpath(root, job)
    tree[rel.split('/')[0]] += len(files)
res['tree'] = dict(tree)
res['root_files'] = sorted(f for f in os.listdir(job) if os.path.isfile(os.path.join(job, f)))[:80]
res['main_files'] = {f: os.path.getsize(os.path.join(job, 'main', f)) for f in sorted(os.listdir(os.path.join(job, 'main')))} if os.path.isdir(os.path.join(job, 'main')) else {}
# 2. strings mentioning grating in every non-subm/mem file
pat = re.compile(rb'(?i)(grat|w-19|19-w|15-w|19w4|bearing|cross ?bar|tread|serrat|band)')
hits = []
for root, dirs, files in os.walk(job):
    rel = os.path.relpath(root, job)
    if rel.split('/')[0] in ('subm', 'mem'):
        continue
    for f in files:
        fp = os.path.join(root, f)
        try:
            if os.path.getsize(fp) > 400e6: continue
            b = open(fp, 'rb').read()
        except OSError:
            continue
        for m in pat.finditer(b):
            s = max(0, m.start() - 48); e = min(len(b), m.end() + 96)
            ctx = re.sub(rb'[^ -~]', b'.', b[s:e]).decode()
            hits.append((os.path.relpath(fp, job), m.start(), ctx))
            if len(hits) > 600: break
res['string_hits'] = hits[:600]
res['string_hit_files'] = dict(collections.Counter(h[0] for h in hits))
# 3. piece table slots: grating vs others
b = open(os.path.join(job, 'subm', 'subm_idx'), 'rb').read()
key = slot_size(b); Lo = LAYOUTS[key]; S = Lo['slot']
res['slot_layout'] = str(key)
pieces = read_pieces(job)
gr = {k: p for k, p in pieces.items() if re.match(r'G[TR]\d', p['name'])}
res['n_grating_pieces'] = len(gr)
slots = {}
for k in list(gr)[:12]:
    s = b[k * S:(k + 1) * S]
    slots[str(k)] = dict(name=gr[k]['name'], p=gr[k], hex=s.hex(),
                         f64=[(o, round(v, 6)) for o in range(0, S - 8, 2) for v in [struct.unpack('>d', s[o:o + 8])[0]]
                              if np.isfinite(v) and 1e-4 < abs(v) < 1e5 and abs(v * 64 - round(v * 64)) < 1e-9][:200])
res['grating_slots'] = slots
# 4. grating piece files
files = {}
for k in list(gr)[:12]:
    fp = os.path.join(job, 'subm', str(k))
    if not os.path.exists(fp):
        files[str(k)] = 'missing'; continue
    d = open(fp, 'rb').read()
    r = brep.parse(d)
    info = dict(size=len(d), head=d[:0x2C].hex())
    if r is not None:
        V, F = r
        used = sorted({i for f in F for i in f})
        info.update(nv=len(V), nf=len(F), ptp=np.round(np.ptp(V[used], 0), 4).tolist(), lo=np.round(V[used].min(0), 4).tolist(),
                    face_sizes=collections.Counter(len(f) for f in F).most_common(8))
        nv, nf, ne = struct.unpack('>3I', d[0x1C:0x28])
        t0 = 0x2C + 28 * nv + 10 * ne + 22 * nf
        info['tail_len'] = len(d) - t0
        info['tail_hex'] = d[t0:t0 + 1600].hex()
        info['tail_f64'] = [(o, round(v, 6)) for o in range(t0, min(len(d) - 8, t0 + 4000), 2) for v in [struct.unpack('>d', d[o:o + 8])[0]]
                            if np.isfinite(v) and 1e-4 < abs(v) < 1e5 and abs(v * 64 - round(v * 64)) < 1e-9][:300]
        sh = brep.solid(V, F)
        if sh is not None:
            from OCP.GProp import GProp_GProps
            from OCP.BRepGProp import BRepGProp
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
            info['vol_in3'] = abs(g.Mass()) / 25.4 ** 3
            info['steel_lb_if_solid'] = info['vol_in3'] * 0.2836
            info['sds2_wt'] = gr[k]['wt']
        # distinct coordinate levels (bars would give many)
        for a in range(3):
            info[f'levels_{a}'] = len(np.unique(np.round(V[used][:, a], 3)))
        info['V_first'] = np.round(V[used][:60], 4).tolist()
    files[str(k)] = info
res['grating_files'] = files
# 5. owning members and their material block bytes
mems, _ = read_members(job)
own = []
for m in mems:
    try:
        main, inst = material_instances(job, m.id, pieces)
    except Exception:
        continue
    for sid, M, o in inst:
        if sid in gr:
            mb = open(os.path.join(job, 'mem', str(m.id)), 'rb').read()
            v = struct.pack('>i', sid) if len(mb) else b''
            offs = [mm.start() for mm in re.finditer(re.escape(struct.pack('>i', sid)), mb)][:4]
            offs16 = [mm.start() for mm in re.finditer(re.escape(struct.pack('>H', sid)), mb)][:8]
            own.append(dict(member=m.id, type=m.type, section=(m.section.name if m.section else None), sid=sid, name=gr[sid]['name'],
                            M=np.round(M, 4).tolist(), o=np.round(o, 3).tolist(), mem_size=len(mb), offs32=offs, offs16=offs16,
                            mem_strings=[x.decode() for x in re.findall(rb'[ -~]{4,}', mb)][:60]))
            if len(own) <= 3:
                X = offs[0] if offs else (offs16[0] if offs16 else 0)
                own[-1]['block_hex'] = mb[max(0, X - 0x6C - 64):X + 600].hex()
            break
    if len(own) >= 30: break
res['owners'] = own
json.dump(res, open(outp, 'w'), default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print(job, 'grating pieces', len(gr), 'string hits', len(hits), dict(collections.Counter(h[0] for h in hits)))
