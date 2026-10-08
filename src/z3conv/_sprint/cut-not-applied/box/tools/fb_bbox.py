"""fb_bbox.py STEP_PARTS.jsonl.gz : flat-bar parts ('F.B AxB') - bbox extents (dx, dy, dz) sorted, to see whether toe plates / stringers stand on edge"""
import sys, json, gzip, collections
c = collections.Counter(); ex = collections.defaultdict(list)
for l in gzip.open(sys.argv[1], 'rt'):
    s = json.loads(l); n = s.get('name') or ''
    if not n.upper().startswith('F.B') or not s.get('bbox'): continue
    b = s['bbox']; d = [round(b[3] - b[0], 1), round(b[4] - b[1], 1), round(b[5] - b[2], 1)]
    key = n.split(' [')[0]
    c[key] += 1
    if len(ex[key]) < 4: ex[key].append(d)
for k, v in c.most_common(10): print(k, v, 'bbox dx,dy,dz examples', ex[k])
