"""Field statistics over SDS2 mem/ records: which offsets hold doubles/ints/strings.

usage: python mem_stats.py <job_dir> [header_len]
"""
import sys, os, struct, re, collections, math

job = sys.argv[1]
H = int(sys.argv[2]) if len(sys.argv) > 2 else 846
md = os.path.join(job, "mem")
recs = {}
for n in os.listdir(md):
    if n.isdigit():
        recs[int(n)] = open(os.path.join(md, n), "rb").read()
print("records:", len(recs), "min/max id", min(recs), max(recs))

for name in ("mem_ctl", "mem_idx", "mem_list"):
    b = open(os.path.join(md, name), "rb").read()
    strs = re.findall(rb"[ -~]{3,}", b)
    print(f"== {name}: {len(b)} bytes; first 64 hex: {b[:64].hex()}")
    print("   strings:", [s.decode() for s in strs[:25]])

# size structure
sizes = collections.Counter(len(b) for b in recs.values())
print("distinct sizes:", len(sizes), "; (size-846) gcd-ish:", sorted({(s - H) for s in sizes})[:30])

# header double stats
print(f"\n== 8-byte slots in first {H} bytes (big-endian double view)")
for off in range(0, H - 7, 8):
    vals = []
    for b in recs.values():
        if len(b) < off + 8: continue
        v = struct.unpack(">d", b[off:off + 8])[0]
        vals.append(v)
    ok = [v for v in vals if not math.isnan(v) and (v == 0 or 1e-4 < abs(v) < 1e8)]
    nz = [v for v in ok if v != 0]
    if len(ok) < 0.95 * len(vals):
        # maybe ints
        i32 = collections.Counter(struct.unpack(">ii", b[off:off + 8]) for b in recs.values() if len(b) >= off + 8)
        print(f"{off:04x} non-double; top int32 pairs {i32.most_common(4)} distinct={len(i32)}")
        continue
    if not nz:
        print(f"{off:04x} always 0"); continue
    d = len(set(round(v, 4) for v in ok))
    print(f"{off:04x} dbl nz={len(nz)/len(vals):.2f} min={min(nz):.4g} max={max(nz):.4g} distinct={d} ex={[round(v,3) for v in nz[:4]]}")

# strings anywhere in records
sc = collections.Counter()
for b in recs.values():
    for s in re.findall(rb"[A-Za-z0-9_#\-. ]{4,}", b):
        sc[s] += 1
print("\ncommon strings in mem records:", [(s.decode(), c) for s, c in sc.most_common(30)])

