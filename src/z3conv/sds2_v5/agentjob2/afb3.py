"""Fallback pieces of a job (pieces.csv) through a tree's own brep_placed: how many get SDS2's B-rep now.
usage: afb3.py <decode dir> <job dir> <pieces.csv>"""
import sys, csv, collections, json, os
import numpy as np
sys.path.insert(0, sys.argv[1]); job, pc = sys.argv[2], sys.argv[3]
import to_step2 as T
from piece_table import read_pieces
from sds2job import read_shapes
FB = ('profile_fallback', 'plate_fallback', 'bent_plate_fallback', 'plate_hull_fallback', 'vertex_box_fallback', 'piece_table_standin')
rows = list(csv.DictReader(open(pc)))
fb = collections.Counter(int(x['piece']) for x in rows if x['builder'] in FB)
P = read_pieces(job)
if hasattr(T, 'SHAPES'):
    T.SHAPES.clear(); T.SHAPES.update(read_shapes(job))
T.SHARED = False
c = collections.Counter(); ex = collections.defaultdict(list)
for sid, n in fb.items():
    p = P.get(sid)
    if p is None:
        c['not in table'] += n; continue
    sh = T.brep_placed(job, sid, p, np.eye(3), np.zeros(3))
    key = (job, sid)
    if sh is None:
        why = T.BREP_WHY.get(key, '?')
        why = why.split(' (')[0] if why.startswith('piece B-rep volume') is False else 'volume vs weight outside 0.6-1.6'
    elif key in getattr(T, 'UNVALIDATED', ()):
        why = 'NOW exact, unvalidated (table unreadable)'
    elif key in getattr(T, 'RIMS_CLOSED', ()):
        why = 'NOW exact, rims closed' + (' + section' if key in getattr(T, 'VALIDATED_BY_SECTION', ()) else '')
    elif key in getattr(T, 'VALIDATED_BY_SECTION', ()):
        why = 'NOW exact, validated by section'
    else:
        why = 'NOW exact'
    c[why] += n
    if len(ex[why]) < 3: ex[why].append((sid, p['name'][:20]))
print(json.dumps(dict(job=os.path.basename(job), tree=sys.argv[1].split('/')[-3], instances=sum(fb.values()), by=dict(c), ex=dict(ex))))
