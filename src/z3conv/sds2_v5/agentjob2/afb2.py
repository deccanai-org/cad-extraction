"""Why approximate pieces don't use the stored B-rep, summarised per job, for one or more decoder trees.
usage: afb2.py <job dir> <pieces.csv> <decode dir> [<decode dir> ...]"""
import sys, csv, collections, json, importlib, os
import numpy as np
job, pc, trees = sys.argv[1], sys.argv[2], sys.argv[3:]
rows = list(csv.DictReader(open(pc)))
FB = ('profile_fallback', 'plate_fallback', 'bent_plate_fallback', 'plate_hull_fallback', 'vertex_box_fallback', 'piece_table_standin')
fb = collections.Counter(int(x['piece']) for x in rows if x['builder'] in FB)
names = {int(x['piece']): x['name'] for x in rows}
res = {}
for t in trees:
    for m in ('brep', 'piece_table'):
        sys.modules.pop(m, None)
    sys.path.insert(0, t)
    brep = importlib.import_module('brep'); PT = importlib.import_module('piece_table')
    sys.path.pop(0)
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    P = PT.read_pieces(job)
    c = collections.Counter(); ci = collections.Counter(); ex = collections.defaultdict(list)
    for sid, ninst in fb.items():
        p = P.get(sid)
        try:
            b = open(os.path.join(job, 'subm', str(sid)), 'rb').read()
            r = brep.parse(b)
        except Exception as e:
            r = None
        if r is None:
            why = 'no face topology'
        else:
            V, F = r
            sh = brep.solid(V, F)
            if sh is None:
                E = collections.Counter()
                for f in F:
                    for l in brep.loops_of(f):
                        for a, bb in zip(l, l[1:] + l[:1]): E[(min(a, bb), max(a, bb))] += 1
                u = collections.Counter(E.values())
                why = 'does not sew: ' + ('open edges' if u.get(1) else '') + (' nonmanifold edges' if any(k > 2 for k in u) else '')
            elif p is None or not 0 < p['wt'] < 1e9:
                why = 'solid ok, no weight'
            else:
                g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
                rr = abs(g.Mass()) / 25.4 ** 3 * 0.2836 / p['wt']
                why = 'solid ok, ratio in 0.6-1.6' if 0.6 < rr < 1.6 else f'solid ok, ratio {"<0.6" if rr <= 0.6 else ">1.6"}'
        c[why] += 1; ci[why] += ninst
        if len(ex[why]) < 4: ex[why].append((sid, names.get(sid)))
    res[t] = dict(pieces=dict(c), instances=dict(ci), examples={k: v for k, v in ex.items()})
print(json.dumps(dict(job=os.path.basename(job), fallback_pieces=len(fb), fallback_instances=sum(fb.values()), trees=res)))
