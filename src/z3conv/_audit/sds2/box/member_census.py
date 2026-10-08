#!/usr/bin/env python3
"""Member census of an SDS/2 job with the v5.3 reader: member types, sections, end points, member-file sizes; on a
calibration failure, the mem_idx facts the calibration uses (type markers, slot-size candidates, member files).
usage: member_census.py PIPE JOB OUT_JSON"""
import sys, os, re, json, collections, struct, traceback
import numpy as np
PIPE, job, out = sys.argv[1:4]
sys.path.insert(0, os.path.join(PIPE, 'decode'))
import sds2job

md = os.path.join(job, 'mem')
idx = open(os.path.join(md, 'mem_idx'), 'rb').read()
ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
res = {'version': sds2job.read_version(job), 'mem_idx_bytes': len(idx), 'member_files': len(ids),
       'member_file_bytes': sum(os.path.getsize(os.path.join(md, str(n))) for n in ids),
       'subm_files': sum(1 for x in os.listdir(os.path.join(job, 'subm')) if x.isdigit()) if os.path.isdir(os.path.join(job, 'subm')) else 0}
pos = [m.start() for m in re.finditer(rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|MISC|Ref Point)\x00", idx)]
res['calibrate_type_markers'] = len(pos)
res['type_strings_in_mem_idx'] = dict(collections.Counter(m.group(1).decode('latin-1') for m in re.finditer(
    rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|HORIZONTAL BRACE|MISC|STAIR|JOIST|Wall|Ref Point|DWF Import|IFC Import|SDNF Import|DGN Import|Reference Model|ReferenceModel|GRATING|DECKING|HANDRAIL|EMBED)\x00", idx)))
res['slot_candidates'] = [s for s in (1280, 1416, 2494, 2944, 2976, 3204, 3404, 3600)
                          if len(idx) >= 256 and (len(idx) - 256) % s == 0 and (len(idx) - 256) // s > (max(ids) if ids else 0)]
try:
    shapes = sds2job.read_shapes(job)
    res['shapes'] = len(shapes)
except Exception as e:
    shapes = {}; res['shapes_error'] = f'{type(e).__name__}: {e}'
try:
    mem, L = sds2job.read_members(job)
    res['layout'] = {k: v for k, v in L.items() if isinstance(v, (int, float, str))}
    res['members'] = len(mem)
    res['types'] = dict(collections.Counter(m.type for m in mem).most_common(40))
    nos = collections.Counter(); deg = collections.Counter(); fsz = collections.Counter()
    for m in mem:
        p1 = np.asarray(m.p1, float); p2 = np.asarray(m.p2, float)
        if m.section is None:
            nos[m.type] += 1
        if not (np.isfinite(p1).all() and np.isfinite(p2).all()) or np.linalg.norm(p2 - p1) < 1e-6:
            deg[m.type] += 1
        sz = os.path.getsize(os.path.join(md, str(m.id))) if os.path.exists(os.path.join(md, str(m.id))) else None
        fsz[(m.type, 'small<1KB' if (sz or 0) < 1024 else 'ge1KB')] += 1
    res['no_section_by_type'] = dict(nos.most_common(20)); res['degenerate_by_type'] = dict(deg.most_common(20))
    res['member_file_size_by_type'] = {f'{k[0]}|{k[1]}': v for k, v in fsz.most_common(30)}
except Exception as e:
    res['read_members_error'] = f'{type(e).__name__}: {e}'
    res['trace'] = traceback.format_exc()[-800:]
    for slot in res['slot_candidates']:
        try:
            r = sds2job._sparse_try(job, idx, ids, shapes, slot, res['version'])
            res.setdefault('sparse_try', {})[str(slot)] = None if r is None else {'typed': r[1], 'layout': r[0]}
        except Exception as e2:
            res.setdefault('sparse_try', {})[str(slot)] = f'{type(e2).__name__}: {e2}'
json.dump(res, open(out, 'w'), indent=1, default=str)
print(json.dumps(res, default=str)[:3000])
