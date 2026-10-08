"""Auto-detect mem_idx slot layout for any SDS2 version.

slot size  = modal spacing between member-type strings (COLUMN/BEAM/...) in mem_idx
type off   = position of the type string within a slot
p1 off     = where mem/<n>'s left point (+0x48, 24 bytes) sits inside slot n
p2 off     = offset (after p1) holding a second point for most beams/columns
sec/roll   = look near p2 using the 7.243 relative layout, report both
usage: python calibrate.py <job_dir>
"""
import os, sys, re, collections, struct
import numpy as np

def calibrate(job, verbose=True):
    md = os.path.join(job, "mem")
    idx = open(os.path.join(md, "mem_idx"), "rb").read()
    pos = [m.start() for m in re.finditer(rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|MISC|Ref Point)\x00", idx)]
    sp = collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1))
    slot = sp.most_common(1)[0][0]
    toff = collections.Counter(p % slot for p in pos).most_common(1)[0][0]
    ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
    # p1: find mem/n[0x48:0x60] inside slot n
    p1c = collections.Counter()
    for n in ids[:400]:
        b = open(os.path.join(md, str(n)), "rb").read(0x60)
        k = b[0x48:0x60]
        if len(k) < 24 or not any(k): continue
        s = idx[n * slot:(n + 1) * slot]
        j = s.find(k)
        if j >= 0: p1c[j] += 1
    p1 = p1c.most_common(1)[0][0] if p1c else None
    # p2: best offset whose triple differs from p1 but is axis-aligned-ish for many members
    p2c = collections.Counter()
    np.seterr(all="ignore")
    for n in ids[:1500]:
        s = idx[n * slot:(n + 1) * slot]
        if len(s) < slot or p1 is None: continue
        a = np.frombuffer(s[p1:p1 + 24], dtype=">f8")
        for off in range(p1 + 24, min(slot - 24, p1 + 400), 2):
            q = np.frombuffer(s[off:off + 24], dtype=">f8")
            if not np.isfinite(q).all() or np.abs(q).max() > 1e6: continue
            dd = q - a
            L = np.linalg.norm(dd)
            if 12 < L < 5000 and (np.sum(np.abs(dd) < 1e-3) >= 2):
                p2c[off] += 1
    p2 = p2c.most_common(1)[0][0] if p2c else None
    res = dict(slot=slot, type=toff, p1=p1, p2=p2, sec=(p2 + 0x62) if p2 else None, roll=(p2 + 0x68) if p2 else None,
               n_members=len(ids), p1_votes=p1c.most_common(3), p2_votes=p2c.most_common(3))
    if verbose:
        print({k: (hex(v) if isinstance(v, int) and k not in ("slot", "n_members") else v) for k, v in res.items()})
    return res

if __name__ == "__main__":
    for j in sys.argv[1:]:
        print("==", os.path.basename(j.rstrip("\\/")))
        calibrate(j)
