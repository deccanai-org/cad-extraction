"""Tekla profdb.bin (old Xsteel format, gzip): profile names + parameter values.
  value record (25 B): 04 | profile_id i4 | 1 i4 | param_code i4 | 0 i4 | value f8
  index record:        04 | profile_id i4 | 0 i4 | hash i4 | 0x0e i4 | name\0 ...
"""
import gzip, re, struct, collections, sys
def load(p):
    d = open(p, 'rb').read()
    return gzip.decompress(d) if d[:2] == b'\x1f\x8b' else d
def parse(d):
    vals = collections.defaultdict(dict)
    for m in re.finditer(rb'\x04(.{4})\x01\x00\x00\x00(.{4})\x00\x00\x00\x00(.{8})', d, re.S):
        pid = struct.unpack('<i', m.group(1))[0]; pc = struct.unpack('<i', m.group(2))[0]; v = struct.unpack('<d', m.group(3))[0]
        if 0 < pid < 10**6 and 0 < pc < 10**6 and abs(v) < 1e12: vals[pid][pc] = v
    names = {}
    for m in re.finditer(rb'\x04(.{4})\x00\x00\x00\x00(.{4})\x0e\x00\x00\x00([\x20-\x7e\xa0-\xff]{1,80})\x00', d, re.S):
        pid = struct.unpack('<i', m.group(1))[0]; names[pid] = m.group(3).decode("latin1")
    return names, vals
if __name__ == '__main__':
    d = load(sys.argv[1]); names, vals = parse(d)
    print('names', len(names), 'with values', sum(1 for p in names if p in vals))
    byname = {v: k for k, v in names.items()}
    for nm in sys.argv[2:]:
        p = byname.get(nm); print(nm, p, vals.get(p))

def table_names(d):
    return [(m.start(), m.group(1).decode('latin1')) for m in re.finditer(rb'\x04([\x21-\x7e][\x20-\x7e\xa0-\xff]{0,62})\x00{2}', d) if m.start() < len(d)]

def angle_dims(name):
    m = re.match(r'^L(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)$', name)
    return tuple(float(x) for x in m.groups()) if m else None

def resolve_angles(d):
    """L<h>*<b>*<t> name -> catalog parameters, by id (index records) or, for names without an index record,
    by the unique value record set whose h/b/t equal the name's (h 6106, b 6105, t 6242/6241, r1 6111, r2 6229)."""
    names, vals = parse(d)
    out = {}
    byname = {v: k for k, v in names.items()}
    tab = [n for o, n in table_names(d)]
    for nm in set(tab) | set(byname):
        dims = angle_dims(nm)
        if not dims: continue
        h, b, t = dims
        pid = byname.get(nm); how = 'index'
        if pid is None:
            c = [p for p, v in vals.items() if v.get(6106) == h and v.get(6105) == b and v.get(6242) == t and p not in names]
            if len(c) != 1: continue
            pid = c[0]; how = 'unique_values'
        v = vals.get(pid, {})
        if v.get(6106) != h or v.get(6105) != b or v.get(6242) != t: continue
        out[nm] = dict(pid=pid, how=how, h=h, b=b, t=t, t2=v.get(6241), r1=v.get(6111), r2=v.get(6229), area=v.get(6122), kg_m=v.get(6121))
    return out

def full_map(d):
    """every name-table entry -> its parameter dict. The table lists profiles in the same order as their value records;
    names with an index record give anchors (table index -> value-record position); an entry between two anchors with
    the same offset gets the value block at that offset (unambiguous); others are left out."""
    names, vals = parse(d)
    order = []; seen = set()
    for m in re.finditer(rb'\x04(.{4})\x01\x00\x00\x00(.{4})\x00\x00\x00\x00(.{8})', d, re.S):
        p = struct.unpack('<i', m.group(1))[0]
        if p in vals and p not in seen: seen.add(p); order.append(p)
    pos = {p: i for i, p in enumerate(order)}
    tab = [n for o, n in table_names(d)]
    byid = {}
    for p, n in names.items(): byid.setdefault(n, p)
    anchors = [(i, pos[byid[n]]) for i, n in enumerate(tab) if n in byid and byid[n] in pos]
    out = {}
    import bisect
    ai = [a[0] for a in anchors]
    for i, n in enumerate(tab):
        if n in byid and byid[n] in vals:
            out.setdefault(n, dict(pid=byid[n], how='index', vals=vals[byid[n]])); continue
        k = bisect.bisect_left(ai, i)
        if k == 0 or k >= len(anchors): continue
        (i0, p0), (i1, p1) = anchors[k - 1], anchors[k]
        if i0 - p0 != i1 - p1: continue
        j = i - (i0 - p0)
        if 0 <= j < len(order):
            out.setdefault(n, dict(pid=order[j], how='order_between_anchors', vals=vals[order[j]]))
    return out

# ---------------------------------------------------------------- per-model catalog (validated entries only)
FAM_ANGLE, FAM_ROUND = 2, 6
P_ROUND_NAME = re.compile(r'^(?:R\.B|RB|D|ROD|RD|DIA)\s*\xd8?\s*(\d+(?:\.\d+)?)$')        # 'R.B Ø20', 'D20'


def table_entries(d):
    out = []
    for o, n in table_names(d):
        if o + 73 > len(d): continue
        fam = struct.unpack('<i', d[o + 65:o + 69])[0]; code = struct.unpack('<i', d[o + 69:o + 73])[0]
        out.append((o, n, fam, code))
    return out


def model_catalog(d, wanted=None):
    """{name: {kind, dims, src}} for angle (family 2) and round-bar (family 6) entries whose parameter block is identified
    either by the profile's own index record or, without one, by the unique parameter block whose dimensions equal those
    written in the name (several candidate blocks are accepted only when they agree on every dimension used)."""
    names, vals = parse(d)
    byname = {}
    for p, n in names.items(): byname.setdefault(n, p)
    out = {}
    for o, n, fam, code in table_entries(d):
        if wanted is not None and n not in wanted: continue
        if fam == FAM_ANGLE:
            dims = angle_dims(n)
            if not dims: continue
            h, b, t = dims
            def ok(v): return v.get(6106) == h and v.get(6105) == b and v.get(6242) == t
            p = byname.get(n)
            if p is not None and p in vals and ok(vals[p]):
                cands = [vals[p]]; how = 'index_record'
            else:
                cands = [v for q, v in vals.items() if ok(v) and q not in names]; how = 'unique_dimension_block'
            if not cands: continue
            key = {(v.get(6241), v.get(6111), v.get(6229)) for v in cands}
            if len(key) != 1: continue
            t2, r1, r2 = key.pop()
            if t2 != t or r1 is None or r2 is None or not (0 <= r2 <= r1 <= 3 * t): continue
            out[n] = dict(kind='L', dims=[h, b, t, r1, r2, None, None, None], src=f'profdb.bin family {fam} type {code} ({how}): r1 {r1} r2 {r2}')
        elif fam == FAM_ROUND:
            m = P_ROUND_NAME.match(n)
            if not m: continue
            dd = float(m.group(1))
            def okr(v): return v.get(6109) == dd and not (set(v) & {6105, 6106, 6108})
            p = byname.get(n)
            if p is not None and p in vals and okr(vals[p]):
                how = 'index_record'
            elif any(okr(v) for q, v in vals.items() if q not in names):
                how = 'unique_dimension_block'
            else:
                continue
            out[n] = dict(kind='CIRC', dims=[dd / 2], src=f'profdb.bin family {fam} type {code} ({how}): diameter {dd}')
    return out
