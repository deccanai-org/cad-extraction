"""Self-calibrating reader for main/job_mtrl across SDS2 versions.

Findings so far:
  7.2xx / 7.3xx : big-endian f64, 510-B records, name at +0, d +0x1A, bf +0x22, tf +0x2A, tw +0x32, k +0x3A, wt +0x42
  7.4xx (2015)  : LITTLE-endian f64, 390-B records, name at +0, d +0x1C, bf +0x24, tf +0x2C, tw +0x34, wt +0x44
Nothing is assumed: record size = modal spacing of section names; byte order and field offsets are the ones
that reproduce (a) the nominal weight in W-shape names (W18x35 -> 35.0) and (b) AISC d/bf for known shapes.
usage (diagnostic): python mtrl_calib.py <job_dir>
"""
import os, re, sys, struct, collections

AISC = {"W18x35": (17.7, 6.0, 0.425, 0.3), "W12x19": (12.2, 4.01, 0.35, 0.235), "W14x22": (13.7, 5.0, 0.335, 0.23),
        "W8x31": (8.0, 8.0, 0.435, 0.285), "W10x12": (9.87, 3.96, 0.21, 0.19), "W24x55": (23.6, 7.01, 0.505, 0.395),
        "W21x44": (20.7, 6.5, 0.45, 0.35), "W16x26": (15.7, 5.5, 0.345, 0.25), "W27x84": (26.7, 10.0, 0.64, 0.46),
        "W30x99": (29.7, 10.5, 0.67, 0.52), "W14x90": (14.0, 14.5, 0.71, 0.44), "W12x26": (12.2, 6.49, 0.38, 0.23)}
NAME_RX = re.compile(rb"(?<![ -~])((?:W|HSS|L|C|MC|WT|S|HP|PIPE)\d[\dxX./ -]*)\x00")


def calibrate_mtrl(b):
    pos = [(m.start(), m.group(1).decode()) for m in NAME_RX.finditer(b)]
    if len(pos) < 20:
        raise ValueError("too few section names in job_mtrl")
    sp = collections.Counter(pos[i + 1][0] - pos[i][0] for i in range(len(pos) - 1))
    rec = sp.most_common(1)[0][0]
    base = collections.Counter(p % rec for p, _ in pos).most_common(1)[0][0]
    Ws = [(p, n) for p, n in pos if re.fullmatch(r"W\d+x[\d.]+", n)]
    best = None
    # 7.0/7.1 store the fields as 32-bit floats (178-B records, EC-48); 7.2+ as 64-bit doubles
    for endian in (">", "<"):
        for ft, w in (("d", 8), ("f", 4)):
            tol = 1e-6 if ft == "d" else 1e-3
            wc = collections.Counter()
            for p, n in Ws[:300]:
                wt = float(n.split("x")[1]); r = b[p:p + rec]
                for off in range(0, rec - w):
                    if abs(struct.unpack(endian + ft, r[off:off + w])[0] - wt) < tol * max(1, wt): wc[off] += 1
            dc = collections.Counter()
            for p, n in Ws:
                if n not in AISC: continue
                d, bf, tf, tw = AISC[n]; r = b[p:p + rec]
                for off in range(0, rec - 4 * w):
                    v = struct.unpack(endian + "4" + ft, r[off:off + 4 * w])
                    if abs(v[0] - d) / d < 0.02 and abs(v[1] - bf) / bf < 0.03: dc[off] += 1
            score = (dc.most_common(1)[0][1] if dc else 0, wc.most_common(1)[0][1] if wc else 0)
            if best is None or score > best[0]:
                best = (score, endian, ft, wc, dc)
    (dvotes, wvotes), endian, ft, wc, dc = best
    if not dc or not wc:
        raise ValueError("job_mtrl: no byte order / float width reproduces AISC dims and W weights")
    return dict(rec=rec, base=base, endian=endian, ftype=ft, d_off=dc.most_common(1)[0][0], weight_off=wc.most_common(1)[0][0],
                votes=dict(weight=wvotes, dims=dvotes, w_records=len(Ws)))


if __name__ == "__main__":
    job = sys.argv[1]
    b = open(os.path.join(job, "main", "job_mtrl"), "rb").read()
    L = calibrate_mtrl(b)
    print(len(b), {k: (hex(v) if isinstance(v, int) else v) for k, v in L.items()})
    e = L["endian"]; out = []
    for k in range((len(b) - L["base"]) // L["rec"]):
        r = b[L["base"] + k * L["rec"]: L["base"] + (k + 1) * L["rec"]]
        m = re.match(rb"[ -~]+", r)
        if m and re.match(rb"W18x35|W14x90|L4x4x3/8|HSS8x8", m.group()):
            d, bf, tf, tw = struct.unpack(e + "4d", r[L["d_off"]:L["d_off"] + 32])
            wt = struct.unpack(e + "d", r[L["weight_off"]:L["weight_off"] + 8])[0]
            out.append((k, m.group().decode(), round(d, 3), round(bf, 3), round(tf, 3), round(tw, 3), round(wt, 2)))
    print(out[:6])
