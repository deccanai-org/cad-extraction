"""Tekla bolt groups for the 'new' engines (7.5x-8.x, record-discovered layouts) -> bolt solids + holes.

Reverse-engineered from Tekla IFC exports joined to the DB1 by GUID (IfcMechanicalFastener Tag 'ID<guid>' == the GUID
string stored with the object in the DB1). Validated on 7.82 (1,041 groups), 8.07 (512) and 8.53 (2,674).

A bolt group is a member-like record (it has the member prefix: origin + length doubles, two point refs = the group's
layout line, a csys ref, an attribute ref) whose attribute record has obj_type 10 at +13:
  * 7.x and early files: group record in the 65-byte member table, attribute record in the PART attribute table, the
    "profile" is the bolt string  MM<d>*<L>/<slot x>/<slot y>/<tolerance>/<?>/<search length>/<grip centre z>/<?>/<flags>/<?>/<grip>
  * 8.x: group record in the 65-byte (8.07) or 73-byte (8.44/8.53) member table, attribute record in its own table
    (stride 317 on 8.53, 365 on 8.07), fields anchored at the record END: d S-48, slot x S-44, slot y S-40,
    tolerance S-36, grip centre z S-24, flags S-16 (int), length S-12 (float32); bolt count at +29 (+(S-317));
    bolt standard string at +165 (+(S-317)).
Bolt positions: the group's pattern record (same family as contour outlines, stride 341): u[10]@21, v[10]@61 float32
in the group frame, count = index of INT_MAX in the int array @221, >10 bolts continue in records with the same key
(index @13). Group frame: x, y = the record's csys (x signed toward the far layout point, as for members), z = x cross y.
Bolt axis = -z; the head is on the +z side. Flags (decimal digits d5..d0): d5 = 1 holes only (no bolt);
washers = d4 + d3 + d2 (d4 = head side), nuts = d1 + d0.
The parts a group connects: relation records (type 10) bolt @17 -> part @21 (same table as part cuts, 8.x).
"""
import math, re, collections
import numpy as np

SENT = 2147483647
NUM = r'(-?\d+(?:\.\d+)?)'
P_MM = re.compile(r'^MM\s*(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)((?:/[^/]*)*)$')
LAYS = (dict(name='m65', stride=65, attr=13, p1=17, p2=21, poly=25, csys=29, xyz=33),
        dict(name='m73', stride=73, attr=13, p1=21, p2=25, poly=29, csys=33, xyz=41))


def parse_mm(prof):
    """old-style bolt string -> dict or None (fields that do not parse are None)"""
    m = P_MM.match((prof or '').strip())
    if not m: return None
    d, L = float(m.group(1)), float(m.group(2))
    f = [x for x in m.group(3).split('/')[1:]]

    def fl(i):
        try: return float(f[i])
        except (IndexError, ValueError): return None
    flags = None
    try: flags = int(f[7])
    except (IndexError, ValueError): pass
    return dict(d=d, L=L, slot_x=fl(0), slot_y=fl(1), tol=fl(2), search=fl(4), zc=fl(5), flags=flags, grip=fl(9), src='mm_string')


def flag_bits(flags):
    """decimal-digit assembly flags -> dict(bolt, w1, w2, w3, n1, n2)"""
    if flags is None or flags < 0 or any(c not in '01' for c in str(flags)) or flags >= 10 ** 6: return None
    s = '%06d' % flags
    return dict(bolt=s[0] == '0', w1=s[1] == '1', w2=s[2] == '1', w3=s[3] == '1', n1=s[4] == '1', n2=s[5] == '1')


class BoltDecoder:
    def __init__(self, db, pts, cs, lay):
        self.db = db; self.pts = pts; self.cs = cs; self.lay = lay
        self.P = pts[lay.get('pts', 0)] if pts else None
        self.C = next((c for c in cs if c['stride'] == lay.get('csys_stride') and c['k'] == lay.get('csys_k') and c['key'] == lay['csys_key']), None) if cs else None
        self.stats = collections.Counter()

    # ---------------------------------------------------------------- group records
    def records(self):
        """-> list of group dicts (frame + attribute key + pattern key)"""
        db = self.db
        if self.P is None or self.C is None: return []
        cmap, ckeys = self.C['map'], self.C['keys']
        from db1dec import inkeys
        out = []; seen = set()
        for s, recs in db.runs:
            # a table of 65/73-byte records can be segmented with a multiple stride (130, 195, ...): try both member layouts on
            # every run that is wide enough and keep, per run, the layout under which more bolt records resolve
            best = None
            for L in LAYS:
                if s < L['stride']: continue
                a = db.I(recs + L['attr']); ao = db.lookup(a)
                ok = ao >= 0
                ob = np.where(ok, db.I(np.where(ok, ao, 0) + 13), -1)
                sel = np.nonzero(ok & (ob == 10))[0]
                if not len(sel): continue
                R = recs[sel]
                X = np.stack([db.D(R + L['xyz'] + 8 * i) for i in range(4)], 1)
                p1 = db._pt(self.P, db.I(R + L['p1'])); p2 = db._pt(self.P, db.I(R + L['p2']))
                Cv = db.I(R + L['csys'])
                good = (np.all(np.isfinite(X), 1) & (np.abs(X[:, :3]) < 1e8).all(1) & np.all(np.isfinite(p1), 1)
                        & np.all(np.isfinite(p2), 1) & inkeys(ckeys, Cv))
                if good.sum() == 0: continue
                if best is None or good.sum() > best[0]: best = (int(good.sum()), L, R, X, p1, p2, Cv, good)
            if best is None: continue
            _, L, R, X, p1, p2, Cv, good = best
            self.stats[('records', L['name'], int(s))] += int(good.sum())
            for i in np.nonzero(good)[0]:
                off = int(R[i])
                if off in seen: continue
                seen.add(off)
                O = X[i, :3]; x, y = cmap[int(Cv[i])]
                y = y - (y @ x) * x; y = y / np.linalg.norm(y)
                Lr = (p2[i] - p1[i]) @ x; t0 = (O - p1[i]) @ x
                sgn = 1 if abs(t0) <= abs(t0 - Lr) else -1
                out.append(dict(off=off, stride=s, lay=L['name'], seq=int(db.I([off + 9])[0]), O=O, x=sgn * x, y=y,
                                attr=int(db.I([off + L['attr']])[0]), poly=int(db.I([off + L['poly']])[0]), Lline=float(X[i, 3])))
        # 8.85 / 9.x: the group is split over records keyed by the group key: a header in the 33-byte table
        # [key attr@13 ? p1@21 p2@25 pattern@29] and a placement [key csys@13 origin@17 L@41] (the 49-byte table)
        n0 = len(out); hdr = {}; have = {g['seq'] for g in out}
        for s, recs in db.runs:
            if s < 33 or s % 33: continue
            a = db.I(recs + 13); ao = db.lookup(a); ok = ao >= 0
            ob = np.where(ok, db.I(np.where(ok, ao, 0) + 13), -1)
            for o in recs[ob == 10]: hdr.setdefault(int(db.I([int(o) + 9])[0]), int(o))
        for k, h in hdr.items():
            if k in have: continue
            po = None
            for o in db.lookup_all(k):
                c_ = int(db.I([o + 13])[0])
                if c_ in cmap:
                    X = db.D(o + 17 + 8 * np.arange(4))
                    if np.all(np.isfinite(X)) and np.all(np.abs(X[:3]) < 1e8) and X[3] > 0: po = o; break
            if po is None: self.stats['composite_no_placement'] += 1; continue
            p1 = db._pt(self.P, db.I([h + 21]))[0]; p2 = db._pt(self.P, db.I([h + 25]))[0]
            if not (np.all(np.isfinite(p1)) and np.all(np.isfinite(p2))): self.stats['composite_no_points'] += 1; continue
            O = db.D(po + 17 + 8 * np.arange(3)); Lline = float(db.D([po + 41])[0]); x, y = cmap[int(db.I([po + 13])[0])]
            y = y - (y @ x) * x; y = y / np.linalg.norm(y)
            Lr = (p2 - p1) @ x; t0 = (O - p1) @ x
            sgn = 1 if abs(t0) <= abs(t0 - Lr) else -1
            out.append(dict(off=h, stride=33, lay='composite', seq=k, O=O, x=sgn * x, y=y, attr=int(db.I([h + 13])[0]),
                            poly=int(db.I([h + 29])[0]), Lline=Lline))
        self.stats['composite_records'] = len(out) - n0
        self.stats['group_records'] = len(out)
        return out

    # ---------------------------------------------------------------- attributes
    def attributes(self, g, prof_fn=None):
        db = self.db
        rr = db.lookup_all(g['attr'])
        rr = [o for o in rr if int(db.I([o + 13])[0]) == 10]
        if not rr: return None
        o = rr[0]; S = int(db.lookup_stride([g['attr']])[0])
        # 7.x: bolt string in the part attribute table
        if S == self.lay.get('attr_stride') and prof_fn is not None:
            prof = prof_fn(g['attr'])
            a = parse_mm(prof)
            if a:
                a['prof'] = prof
                std = self._std(o, S, 285 if S == 389 else None)
                a['standard'] = std
                return a
        # 8.x / 9.x: own table. Fields sit at fixed offsets after a variable block: 8.53 / 8.85 (stride 317) and 9.08 (321) shift 0,
        # 8.07 (365) shift 48; the shift is read from the record's own 'SCREW' type string (at 59 + shift)
        if S >= 300:
            raw = db.b[o:o + S]; pos = raw.find(b'SCREW')
            sh = (pos - 59) if 0 <= pos - 59 <= S - 317 else (48 if S == 365 else 0)
            F = lambda k: float(db.F([o + k + sh])[0])
            a = dict(d=F(269), slot_x=F(273), slot_y=F(277), tol=F(281), search=F(289), zc=F(293), flags=int(db.I([o + 301 + sh])[0]),
                     L=F(305), count=int(db.I([o + 29 + sh])[0]), grip=None, src='attr%d' % S, slot_parts=int(db.I([o + 21 + sh])[0]))
            a['standard'] = self._std(o, S, 165 + sh)
            if not (3 <= a['d'] <= 120 and 0 < a['L'] < 3000 and 0 <= a['tol'] < 50): return None
            return a
        return None

    def _std(self, o, S, k):
        if k is None or k >= S: return None
        s = self.db.cstr(o + k, 32)
        return s if s and all(32 <= ord(c) < 127 for c in s) and any(c.isalnum() for c in s) else None

    # ---------------------------------------------------------------- positions
    # pattern record layouts: (u offset, v offset, element type, type-array offset). 7.x-8.85: stride 341, float32 arrays;
    # 9.08: stride 465, float64 arrays (validated on 9.08 ASV: v doubles at 105 = [-114.3, 0, 114.3], INT_MAX at 345 + 4n)
    PAT = {341: (21, 61, 'f', 221), 465: (25, 105, 'd', 345)}

    def positions(self, g):
        db = self.db
        S = int(db.lookup_stride([g['poly']])[0])
        if S not in self.PAT: return None
        ub, vb, kind, tb = self.PAT[S]
        rd = db.F if kind == 'f' else db.D; w = 4 if kind == 'f' else 8
        recs = [r for r in db.lookup_all(g['poly']) if int(db.lookup_stride([g['poly']])[0]) == S]
        byidx = {}
        for r in recs:
            byidx.setdefault(int(db.I([r + 13])[0]), r)
        out = []
        for i in range(len(byidx)):
            r = byidx.get(i)
            if r is None: return None
            u = rd(r + ub + w * np.arange(10)); v = rd(r + vb + w * np.arange(10))
            ty = db.I(r + tb + 4 * np.arange(10)); e = np.nonzero(ty == SENT)[0]
            n = int(e[0]) if len(e) else 10
            if not (np.all(np.isfinite(u[:n])) and np.all(np.isfinite(v[:n])) and np.all(np.abs(u[:n]) < 1e6) and np.all(np.abs(v[:n]) < 1e6)):
                return None
            out += [(float(u[j]), float(v[j])) for j in range(n)]
            if n < 10: break
        return out if out else None

    # ---------------------------------------------------------------- relations bolt -> parts
    def links(self, bolt_seqs, part_seqs):
        """relation table whose records join bolt-group keys to part keys (8.x: stride 69, type 10 @13, bolt @17, part @21)"""
        from db1dec import inkeys
        db = self.db
        bk = np.array(sorted(bolt_seqs), np.int64); pk = np.array(sorted(part_seqs), np.int64)
        if not len(bk) or not len(pk): return {}
        best = None
        # fast path: the part-cut relation table (8.x / 7.82: stride 69, fields 17 / 21) also holds the bolt relations
        cl = getattr(db, 'cut_layout', None)
        cands = [(cl['stride'], cl['parent'], cl['cut']), (cl['stride'], cl['cut'], cl['parent'])] if cl else []
        cands += [(69, 17, 21)]
        for s0, f1, f2 in cands:
            recs = db.bystride.get(s0)
            if recs is None or not len(recs): continue
            n = int((inkeys(bk, db.I(recs + f1)) & inkeys(pk, db.I(recs + f2))).sum())
            if n >= 2 and (best is None or n > best[0]): best = (n, s0, f1, f2)
        if best is not None and best[0] < 0.3 * len(bk): best = None
        runs = [] if best is not None else db.runs
        for s, recs in runs:
            if s > 200 or len(recs) < 3: continue
            ints = {f: db.I(recs + f) for f in range(9, s - 3)}
            for f1, v1 in ints.items():
                m1 = inkeys(bk, v1)
                if m1.sum() < 2: continue
                for f2, v2 in ints.items():
                    if f2 == f1: continue
                    n = int((m1 & inkeys(pk, v2)).sum())
                    if n >= 2 and (best is None or n > best[0]): best = (n, s, f1, f2)
        if not best: return {}
        _, s, fb, fp = best
        L = collections.defaultdict(list)
        for st, recs in [(s, db.bystride[s])]:
            b = db.I(recs + fb); p = db.I(recs + fp)
            ok = inkeys(bk, b) & inkeys(pk, p)
            for o_, bb, pp in zip(recs[ok], b[ok], p[ok]):
                L[int(bb)].append((int(o_), int(pp)))
        self.link_layout = dict(stride=s, bolt=fb, part=fp, linked=sum(len(v) for v in L.values()))
        return {k: [p for _, p in sorted(v)] for k, v in L.items()}

    def decode(self, M):
        """-> list of bolt groups with world positions; self.stats filled"""
        prof_cache = {}
        def prof_fn(a):
            if a not in prof_cache: prof_cache[a] = self.db.profile(self.lay, a)
            return prof_cache[a]
        G = self.records()
        out = []
        for g in G:
            a = self.attributes(g, prof_fn)
            if a is None: self.stats['no_attributes'] += 1; continue
            P = self.positions(g)
            if P is None: self.stats['no_positions'] += 1; continue
            if a.get('count') is not None and a['count'] != len(P):
                self.stats['count_mismatch'] += 1; continue          # pattern record does not agree with the group's own bolt count
            fb = flag_bits(a.get('flags'))
            g.update(a); g['flagbits'] = fb; g['uv'] = P
            g['z'] = np.cross(g['x'], g['y'])
            g['world'] = [g['O'] + g['x'] * u + g['y'] * v for u, v in P]
            out.append(g)
        self.stats['groups'] = len(out); self.stats['bolts'] = sum(len(g['uv']) for g in out)
        return out


# ---------------------------------------------------------------- exact line / extruded-region intervals
def _clip_line_poly(a, b, poly):
    """parameters t where the 2D line a + t (b - a) is inside polygon poly (even-odd): sorted crossing list"""
    ts = []
    n = len(poly); d = (b[0] - a[0], b[1] - a[1])
    for i in range(n):
        p = poly[i]; q = poly[(i + 1) % n]
        e = (q[0] - p[0], q[1] - p[1])
        den = d[0] * e[1] - d[1] * e[0]
        if abs(den) < 1e-12: continue
        w = (p[0] - a[0], p[1] - a[1])
        t = (w[0] * e[1] - w[1] * e[0]) / den
        s = (w[0] * d[1] - w[1] * d[0]) / den
        if -1e-9 <= s < 1 - 1e-9: ts.append(t)
    return sorted(ts)


def _inside(pt, poly):
    x, y = pt; c = False; n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-300) + x1: c = not c
    return c


def line_intervals(frame, depth, region, P0, axis, tmin=-5000.0, tmax=5000.0):
    """intervals of t (P0 + t*axis) inside the extruded region (frame (o, Z, X); local z in [0, depth]; region (outer, inners))
    -> list of (t0, t1)"""
    o, Z, X = (np.asarray(v, float) for v in frame)
    Z = Z / np.linalg.norm(Z); X = X - (X @ Z) * Z; X = X / np.linalg.norm(X); Y = np.cross(Z, X)
    R = np.stack([X, Y, Z], 1)
    p = R.T @ (np.asarray(P0, float) - o); dv = R.T @ np.asarray(axis, float)
    lo, hi = tmin, tmax
    if abs(dv[2]) < 1e-12:
        if not (0 <= p[2] <= depth): return []
    else:
        t1, t2 = (0 - p[2]) / dv[2], (depth - p[2]) / dv[2]
        lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
    if lo >= hi: return []
    outer, inners = region
    if math.hypot(dv[0], dv[1]) < 1e-9:
        q = (p[0], p[1])
        inside = _inside(q, outer) and not any(_inside(q, h) for h in inners)
        return [(lo, hi)] if inside else []
    a = (p[0], p[1]); b = (p[0] + dv[0], p[1] + dv[1])
    ts = []
    for poly in [outer] + list(inners):
        ts += _clip_line_poly(a, b, poly)
    ts = sorted(ts)
    out = []
    for i in range(0, len(ts) - 1):
        m = 0.5 * (ts[i] + ts[i + 1])
        q = (a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m)
        if _inside(q, outer) and not any(_inside(q, h) for h in inners):
            s0, s1 = max(ts[i], lo), min(ts[i + 1], hi)
            if s1 > s0 + 1e-6: out.append((s0, s1))
    return out


# ---------------------------------------------------------------- planning: bolt dicts (db1bolts interface) + holes per part
def plan(groups, parts, regions, links, std_fn, washer_t_fn):
    """groups: BoltDecoder.decode() output; parts: {seq: (frame, depth)} written parts; regions: {seq: (outer, inners)};
    links: {group seq: [part seq]} or {} (then every written part pierced within the recorded grip is used).
    -> (bolts_by_group {seq: [bolt dict]}, holes_by_part {part seq: [(bolt dict, z0, z1)]}, stats)"""
    st = collections.Counter(); BG = {}; HP = collections.defaultdict(list)
    # spatial prefilter for the no-links case
    pk = list(parts)
    if pk:
        boxes = {}
        for s in pk:
            fr, dep = parts[s]; reg = regions.get(s)
            if reg is None: continue
            o, Z, X = (np.asarray(v, float) for v in fr); Z = Z / np.linalg.norm(Z); X = X - (X @ Z) * Z; X = X / np.linalg.norm(X); Y = np.cross(Z, X)
            P = np.asarray(reg[0], float); lo2, hi2 = P.min(0), P.max(0)
            cs = np.array([o + X * x + Y * y + Z * z for x in (lo2[0], hi2[0]) for y in (lo2[1], hi2[1]) for z in (0.0, dep)])
            boxes[s] = (cs.min(0), cs.max(0))
        bk = list(boxes); blo = np.array([boxes[s][0] for s in bk]) if bk else None; bhi = np.array([boxes[s][1] for s in bk]) if bk else None
    for g in groups:
        fb = g.get('flagbits') or {}
        holes_only = fb.get('bolt') is False
        d_st = g['d']; L = g['L']; sg = std_fn(g.get('standard'), d_st) if std_fn else None
        ez = np.asarray(g['z'], float); ex = np.asarray(g['x'], float); ey = np.cross(ez, ex)
        nw_head = 1 if fb.get('w1') else 0; nw_2 = int(fb.get('w2', 0)); nw_nut = int(fb.get('w3', 0)); nn = int(fb.get('n1', 0)) + int(fb.get('n2', 0))
        if not fb: nn = 1
        cand = links.get(g['seq']) if links else None
        bolts = []
        for (u, v), P0 in zip(g['uv'], g['world']):
            P0 = np.asarray(P0, float)
            # parts pierced by the bolt axis (line through the bolt point along z)
            if cand is not None:
                pl = [s for s in cand if s in parts and s in regions]
            else:
                if not pk or blo is None: pl = []
                else:
                    reach = max(L, (g.get('grip') or 0)) + 3 * d_st + 50
                    a = P0 - ez * reach; b = P0 + ez * reach
                    lo = np.minimum(a, b) - d_st; hi = np.maximum(a, b) + d_st
                    m_ = np.all(bhi >= lo, 1) & np.all(blo <= hi, 1)
                    pl = [bk[i] for i in np.nonzero(m_)[0]]
            iv = []
            for s in pl:
                fr, dep = parts[s]
                for t0, t1 in line_intervals(fr, dep, regions[s], P0, ez):
                    iv.append((t0, t1, s))
            b = {'c': P0.copy(), 'ex': ex, 'ey': ey, 'ez': ez, 'd': sg['d'] if sg else d_st, 'd_stored': d_st, 'L': L, 'pid': g['seq'],
                 'standard': g.get('standard'), 'std': sg, 'tol': g.get('tol'), 'holes_only': holes_only,
                 'wash_head': nw_head, 'wash_nut': nw_nut, 'wash_2': nw_2, 'nuts': nn, 'axial_decoded': False, 'axial': None, 'p0': P0.copy()}
            zc = g.get('zc'); grip_rec = g.get('grip')
            C = abs(g.get('search') or 0.0)
            if grip_rec and grip_rec > 0 and zc is not None:
                # 7.x bolt string: grip recorded (validated 99.2% on 7.82); holes only in plies within the recorded grip
                lo_r, hi_r = zc - grip_rec / 2, zc + grip_rec / 2
                iv = [(max(x[0], lo_r - 1.0), min(x[1], hi_r + 1.0), x[2]) for x in iv if x[1] > lo_r - 1.0 and x[0] < hi_r + 1.0]
                b['grip'] = (lo_r, hi_r); b['axial'] = 'record'
                if iv:
                    glo = min(x[0] for x in iv); ghi = max(x[1] for x in iv)
                    st['grip_record_vs_plies_ok' if abs(glo - lo_r) < 1.5 and abs(ghi - hi_r) < 1.5 else 'grip_record_vs_plies_differ'] += 1
            elif iv:
                # 8.x: grip not stored; Tekla finds it within the bolt's search ('cut') length around the group plane, so plies
                # of a linked part farther along the axis (a beam's far flange) are neither in the grip nor holed
                if C > 1.0:
                    ivc = [(max(x[0], -C / 2), min(x[1], C / 2), x[2]) for x in iv if x[1] > -C / 2 and x[0] < C / 2]
                    if ivc: iv = ivc
                glo = min(x[0] for x in iv); ghi = max(x[1] for x in iv)
                b['grip'] = (glo, ghi)
                if zc is not None and abs((glo + ghi) / 2 - zc) < 1.0:
                    b['axial'] = 'plies+record_centre'; st['grip_centre_matches_record'] += 1
                else:
                    b['axial'] = 'plies'; st['grip_centre_differs_from_record' if zc is not None else 'grip_from_plies_only'] += 1
            if b.get('grip'):
                zt = b['grip'][1]
                zh = zt + (washer_t_fn(b) if (b['wash_head'] and washer_t_fn) else 0.0)
                b['zh'] = zh; b['c'] = P0 + ez * (zh - L / 2); b['head_up'] = True
                b['axial_decoded'] = b['axial'] in ('record', 'plies+record_centre')
            else:
                st['bolts_without_plies'] += 1
            bolts.append(b)
            for t0, t1, s in iv:
                HP[s].append((b, t0, t1))
            st['bolts'] += 1; st['bolts_holes_only'] += holes_only
            st['bolt_part_holes'] += len(iv)
        BG[g['seq']] = bolts
    return BG, HP, st


# ---------------------------------------------------------------- Tekla's own bolt-assembly dimensions (IFC harvest)
_ASM = None
# DB1 bolt standard string -> Tekla IFC 'Bolt standard', verified per GUID-joined group on 7.82 / 8.07 / 8.53 truth pairs
STD_ALIAS = {'F1852-N-ST': 'F1852', 'F1852-X-ST': 'F1852', 'F1852-N-PT': 'F1852', 'A325-N-PT': 'A325', 'A325-N-ST': 'A325', 'THRD ROD': 'F1554-105'}


def _asm():
    global _ASM
    if _ASM is None:
        import json, os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tekla_bolt_assemblies.json')
        _ASM = {}
        if os.path.exists(p):
            for k, e in json.load(open(p)).items():
                _ASM.setdefault(e['standard'], []).append(e)
    return _ASM


def tekla_geometry(standard, d, fallback=None):
    """head / nut / washer dimensions Tekla itself writes for this bolt standard + diameter (mode over the harvested Tekla IFC exports),
    in the db1bolts.standard_geometry dict format (+ washer_od / washer_t). The DB1 standard string is used as stored, else through the
    verified alias table, else its prefix before the first '-' when that prefix is a harvested standard. None when not harvested."""
    A = _asm(); s = (standard or '').strip()
    if not s or not d: return fallback(standard, d) if fallback else None
    cands = [s, STD_ALIAS.get(s)]
    if '-' in s: cands.append(s.split('-')[0])
    for c in cands:
        if not c or c not in A: continue
        best = min(A[c], key=lambda e: abs(e['d'] - d))
        if abs(best['d'] - d) > 0.06 or 'head' not in best: continue
        hk, haf, hh = best['head']['value']
        out = {'d': float(d), 'head_af': float(haf), 'head_h': float(hh), 'head_kind': hk,
               'nut_af': float(best['nut']['value'][1]) if 'nut' in best else None, 'nut_h': float(best['nut']['value'][2]) if 'nut' in best else None,
               'washer_od': float(best['washer']['value'][0]) if 'washer' in best else None, 'washer_t': float(best['washer']['value'][1]) if 'washer' in best else None,
               'hole_clearance': None, 'family': f"Tekla catalog {c} (harvest: {best['files']} Tekla IFC files, head share {best['head']['share']})",
               'mapping': f'{s} -> {c} d {best["d"]:g}', 'delta_mm': round(abs(best['d'] - d), 3)}
        if out['nut_af'] is None or out['nut_h'] is None:
            fb = fallback(standard, d) if fallback else None
            if fb: out['nut_af'], out['nut_h'] = fb['nut_af'], fb['nut_h']; out['family'] += ' + nut from ' + fb['family']
            else: out['nut_af'], out['nut_h'] = out['head_af'], 0.8 * d; out['family'] += ' + nominal nut'
        return out
    return fallback(standard, d) if fallback else None
