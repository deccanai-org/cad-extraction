# diag_mem.py PIPE_DECODE_DIR JOBDIR : why calibrate()/sparse_layout() fail on a job; read-only
import sys, os, re, collections, struct, json
sys.path.insert(0, sys.argv[1]); job = sys.argv[2]
import sds2job as S
import numpy as np
ver = S.read_version(job)
md = os.path.join(job, 'mem'); idx = open(os.path.join(md, 'mem_idx'), 'rb').read()
ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
print('version', ver, 'mem_idx bytes', len(idx), 'member files', len(ids), ids[:20])
shapes = S.read_shapes(job); print('shapes', len(shapes))
pos = [m.start() for m in re.finditer(rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|HORIZONTAL BRACE|MISC|STAIR|JOIST|Wall|Ref Point|EMBED|ANGLE|PL GIRDER|DWF Import|IFC Import|REFERENCE MODEL|Reference Model)\x00", idx)]
print('type markers', len(pos), collections.Counter(idx[p:p+16].split(b'\0')[0].decode('latin1') for p in pos).most_common(12))
for slot in (1280, 1416, 2494, 2944, 2976, 3204, 3404, 3600):
    if (len(idx) - 256) % slot == 0: print('slot divides', slot, (len(idx) - 256) // slot, 'max id', max(ids) if ids else None)
    print('  slot', slot, 'marker offsets', collections.Counter(p % slot for p in pos).most_common(3))
for fn in ('calibrate', 'sparse_layout'):
    try:
        print(fn, getattr(S, fn)(job, shapes))
    except Exception as e:
        print(fn, 'EXC', type(e).__name__, e)
# member files: work point (+0x48 3xf64) and where it occurs in its own slot for slot 2494
for n in ids:
    with open(os.path.join(md, str(n)), 'rb') as f: h = f.read()
    k = h[0x48:0x60]
    print('mem', n, 'file bytes', len(h), 'wp', struct.unpack('>3d', k) if len(k) == 24 else None)
    for slot in (2494, 2944):
        s = idx[n * slot:(n + 1) * slot]
        print('   slot', slot, 'type@0x988', repr(S._ascii(s[0x988:0x988 + 32])) if len(s) >= 0x9A8 else None,
              'key found at', s.find(k) if len(k) == 24 and any(k) else 'zero-key',
              'p1', struct.unpack('>3d', s[0x112:0x12A]) if len(s) >= 0x12A else None,
              'p2', struct.unpack('>3d', s[0x172:0x18A]) if len(s) >= 0x18A else None,
              'sec@0x1D4', struct.unpack('>h', s[0x1D4:0x1D6])[0] if len(s) >= 0x1D6 else None,
              'sec@0x1D8', struct.unpack('>h', s[0x1D8:0x1DA])[0] if len(s) >= 0x1DA else None)
# all slots of the 2494 family that carry a type string (stale + live)
slot = 2494; typed = []
for n in range(1, (len(idx) - 256) // slot + 1):
    s = idx[n * slot:(n + 1) * slot]
    t = S._ascii(s[0x988:0x988 + 32])
    if t: typed.append((n, t))
print('2494 typed slots', len(typed), typed[:30])
