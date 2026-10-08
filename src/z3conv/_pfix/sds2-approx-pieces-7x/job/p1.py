import sys, os, json, struct, collections
import numpy as np
DEC = sys.argv[1]; job = sys.argv[2]; n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
sys.path.insert(0, DEC)
import brep
from piece_table import read_pieces, kind
pieces = read_pieces(job)
sz = collections.Counter(); ex = collections.defaultdict(list)
for sid, p in pieces.items():
    fp = os.path.join(job, "subm", str(sid))
    if not os.path.exists(fp): continue
    b = open(fp, "rb").read()
    if brep.parse(b) is None:
        sz[(len(b), p["name"][:14])] += 1
        if len(ex[len(b)]) < n: ex[len(b)].append(sid)
print("no-topology files by (size, name):", sz.most_common(40))
for L, sids in sorted(ex.items(), key=lambda x: -sum(v for (l, _), v in sz.items() if l == x[0]))[:6]:
    for sid in sids[:n]:
        p = pieces[sid]; b = open(os.path.join(job, "subm", str(sid)), "rb").read()
        print("=== sid", sid, p["name"], {k: p.get(k) for k in ("L", "W", "T", "wt", "sec")}, "len", len(b))
        for off in range(0, min(len(b), 512), 32):
            ch = b[off:off + 32]
            print("%04x %s" % (off, ch.hex(" ", 4)))
        # doubles at every 8-aligned offset
        ds = [(o, struct.unpack(">d", b[o:o + 8])[0]) for o in range(0, len(b) - 7, 2)]
        print("plausible doubles:", [(hex(o), round(v, 5)) for o, v in ds if 1e-4 < abs(v) < 1e5 and abs(v * 64 - round(v * 64)) < 1e-6 or (1e-3 < abs(v) < 1e4 and len(f'{v:.10g}') < 9)][:60])
