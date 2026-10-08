"""Parse the vertex table of a subm/<n> B-rep and dump the topology section that follows.

Vertex record (28 B): tag u8=0x02, id u24 BE, then x,y,z f64 BE. Records are contiguous; the table ends at the first
non-0x02 tag. Header before it: i32 counts.
usage: python subm_brep.py <job_dir> <n>
"""
import os, sys, struct
import numpy as np

def parse(b):
    # find the start: first offset o where b[o]==2 and 3 following doubles are sane, and next record also valid
    def ok(o):
        if o + 28 > len(b) or b[o] != 2: return False
        v = struct.unpack(">3d", b[o + 4:o + 28])
        return all(np.isfinite(v)) and all(abs(x) < 1e5 for x in v)
    start = next(o for o in range(0, min(len(b), 512)) if ok(o) and ok(o + 28))
    verts, o = [], start
    while ok(o):
        vid = int.from_bytes(b[o + 1:o + 4], "big")
        verts.append((vid, struct.unpack(">3d", b[o + 4:o + 28])))
        o += 28
    return start, verts, o

if __name__ == "__main__":
    job, n = sys.argv[1], int(sys.argv[2])
    b = open(os.path.join(job, "subm", str(n)), "rb").read()
    hdr = struct.unpack(f">{min(16, 64 // 4)}i", b[:64])
    start, verts, end = parse(b)
    print(f"subm/{n}: {len(b)} B; header i32: {hdr}")
    print(f"vertex table @{start:#x}..{end:#x}: {len(verts)} vertices")
    for vid, p in verts: print(f"   id {vid:4d} (x8+{vid % 8}) -> {tuple(round(c, 4) for c in p)}")
    t = b[end:end + 400]
    print("after table (u16 BE):", [struct.unpack('>H', t[i:i + 2])[0] for i in range(0, len(t) - 1, 2)][:160])
