"""why_part.py ID PID [PID..]: which bolts cut holes in this part, their group's source relations (type 10), geometry of axis vs part"""
import sys, os, json, gzip, collections, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ids = {l.strip()[:12]: l.strip() for l in open(os.path.join(ROOT, 'ids.txt'))}
i = ids[sys.argv[1][:12]]
A = json.load(open(f'{ROOT}/runs/audit/{i}.audit.json')); R = json.load(open(f'{ROOT}/runs/audit/{i}.rel10.json'))
rel = collections.defaultdict(set)
for g, p in R['rel10']:
    rel[g].add(p)
for pid in [int(x) for x in sys.argv[2:]]:
    P = A['parts'].get(str(pid))
    bl = [b for b in A['bolts'] if pid in b['hits']]
    print(f'== part {pid} {P}  holes from {len(bl)} bolts')
    for b in bl:
        g = b['gid']
        print(f"   bolt#{b['i']} group {g} {b['prof']} d={b['d']:.2f} L={b['L']} holes_only={b['holes_only']} axial={b['axial']} shift={b['shift']} "
              f"| part in group's type-10 relations: {pid in rel.get(g, set())} | group relations: {sorted(rel.get(g, set()))} | spans {b['spans']}")
