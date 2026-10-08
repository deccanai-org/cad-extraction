"""Scan a subm/<n> file for all vertex records (tag 0x02, id%8==1) at any offset, and parse the 10-byte
topology entries  (u16 a, u16 0x8000, u16 b, u16 c, u16 k)."""
import os, sys, struct
import numpy as np

job, n = sys.argv[1], int(sys.argv[2])
b = open(os.path.join(job, "subm", str(n)), "rb").read()
np.seterr(all="ignore")
verts = []
o = 0
while o + 28 <= len(b):
    if b[o] == 2 and b[o + 1] == 0 and (b[o + 3] % 8 == 1):
        v = struct.unpack(">3d", b[o + 4:o + 28])
        if all(np.isfinite(v)) and all(abs(x) < 1e5 for x in v):
            verts.append((o, int.from_bytes(b[o + 1:o + 4], "big"), v)); o += 28; continue
    o += 1
print(f"subm/{n} {len(b)} B: {len(verts)} vertex-like records")
for off, vid, v in verts: print(f"  @{off:#06x} id {vid:5d} idx {vid // 8:4d}  {tuple(round(c, 4) for c in v)}")
# topology entries
t0 = next((i for i in range(len(b) - 10) if b[i + 2:i + 4] == b"\x80\x00" and b[i + 12:i + 14] == b"\x80\x00"), None)
ents = []
i = t0
while i is not None and i + 10 <= len(b) and b[i + 2:i + 4] == b"\x80\x00":
    a, f, c, d, k = struct.unpack(">5H", b[i:i + 10]); ents.append((a, c, d, k)); i += 10
print(f"topology @{t0:#x}: {len(ents)} entries, ends @{i:#x}")
print("  (a,c,d,k):", ents)
print("  next 120 bytes u16:", [struct.unpack('>H', b[j:j+2])[0] for j in range(i, min(len(b), i + 120), 2)])
