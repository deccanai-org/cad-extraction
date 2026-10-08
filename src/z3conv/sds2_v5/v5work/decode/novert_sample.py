"""List pieces that are placed but yield no vertices; show header bytes of a few to see the variant."""
import os, sys, collections, struct
from instances import material_instances, subm_vertices
from piece_table import read_pieces, kind
job = sys.argv[1]
pieces = read_pieces(job)
bad = collections.Counter(); heads = collections.Counter(); ex = {}
for n in sorted(int(x) for x in os.listdir(os.path.join(job, "mem")) if x.isdigit())[:4000]:
    for sid, M, o in material_instances(job, n, pieces)[1]:
        V = subm_vertices(job, sid)
        if V is None or len(V) < 4:
            p = os.path.join(job, "subm", str(sid))
            h = open(p, "rb").read(16).hex() if os.path.exists(p) else "MISSING"
            heads[h[:16]] += 1; bad[kind(pieces[sid])] += 1; ex.setdefault(h[:16], (sid, pieces[sid]["name"], os.path.getsize(p) if os.path.exists(p) else 0))
print(bad); print([(h, c, ex[h]) for h, c in heads.most_common(10)])
