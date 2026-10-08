#!/usr/bin/env python3
"""Streaming, low-memory STEP (AP214/AP203 as written by OpenCASCADE) indexer for the SDS2 -> STEP outputs.

Literal-prefix regex scans over the memory-mapped file give, per solid (MANIFOLD_SOLID_BREP / BREP_WITH_VOIDS /
FACETED_BREP):
  - the product it belongs to and every placed instance (NAUO + ITEM_DEFINED_TRANSFORMATION chain -> world 4x4,
    instance label = the NAUO name, e.g. 'BEAM #1 / W21x62 (piece 1855, inst 1)')
  - vertex statistics: count, bbox, mean, PCA axes and the extents along them (from the VERTEX_POINTs the OCC writer
    emits inside the solid's entity block - depth-first locality, ownership by file offset)
  - its cylindrical / conical faces: radius, axis point and direction, face sense (.F. = concave: hole wall or fillet),
    whether the face owns a SEAM_CURVE (a full 360 deg cylinder) and the face's own vertices
Nothing is tessellated and no B-rep is built, so a 1-2 GB STEP is indexed in a few hundred MB of RAM.
Units: the file's LENGTH_UNIT is detected (mm / inch / m); every coordinate is returned in millimetres.

usage: python stepidx.py <file.step>        (prints a summary)
"""
import mmap, re, sys, os, time, argparse, collections
import numpy as np

STR = rb"'(?:[^']|'')*'"
STR_RE = re.compile(STR)
REF = re.compile(rb'#(\d+)')
FLT = re.compile(rb'[-+]?(?:\d+\.?\d*|\.\d+)(?:[Ee][-+]?\d+)?')
REP_T = (b'SHAPE_REPRESENTATION', b'ADVANCED_BREP_SHAPE_REPRESENTATION', b'MANIFOLD_SURFACE_SHAPE_REPRESENTATION',
         b'FACETED_BREP_SHAPE_REPRESENTATION', b'GEOMETRICALLY_BOUNDED_SURFACE_SHAPE_REPRESENTATION')


def ent_end(mm, start):
    """offset of the ';' that ends the entity whose body starts at start (quotes respected)"""
    pos = start
    while True:
        e = mm.find(b';', pos)
        if e < 0:
            return len(mm)
        if mm[start:e].count(b"'") % 2 == 0:
            return e
        pos = e + 1


def _strings(b):
    return [m.group(0)[1:-1].replace(b"''", b"'").replace(b'\r', b'').replace(b'\n', b'').decode('latin-1') for m in STR_RE.finditer(b)]


def _refs(b):
    """entity references outside quoted strings (labels such as 'BEAM #12 / ...' contain '#digits')"""
    if b"'" in b:
        b = STR_RE.sub(b"''", b)
    return [int(x) for x in REF.findall(b)]


def _floats(b):
    return [float(x) for x in FLT.findall(b)]


def scan(mm, typ, body=True):
    """all simple entities '#id = TYP(' -> list of (offset of '#', id, body bytes or None)"""
    pat = re.compile(b'= ' + typ + rb'\(')
    out = []
    for m in pat.finditer(mm):
        s = m.start()
        h = mm.rfind(b'#', max(0, s - 24), s)
        if h < 0:
            continue
        try:
            i = int(mm[h + 1:s])
        except ValueError:
            continue
        if body:
            e = ent_end(mm, m.end())
            out.append((h, i, mm[m.end() - 1:e]))
        else:
            out.append((h, i, None))
    return out


def frame(loc, z, x):
    """4x4 from AXIS2_PLACEMENT_3D (location, axis=z, ref_direction=x)"""
    z = np.array(z if z is not None else (0, 0, 1.0), float); z /= np.linalg.norm(z) or 1
    x = np.array(x if x is not None else (1.0, 0, 0), float)
    x = x - z * (x @ z)
    n = np.linalg.norm(x)
    if n < 1e-12:
        x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0]); x = x - z * (x @ z); n = np.linalg.norm(x)
    x /= n
    y = np.cross(z, x)
    M = np.eye(4); M[:3, 0] = x; M[:3, 1] = y; M[:3, 2] = z; M[:3, 3] = loc
    return M


def index_step(path, log=None):
    t0 = time.time()
    f = open(path, 'rb')
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    unit = 1.0
    um = re.search(rb'LENGTH_UNIT\(\)\s*NAMED_UNIT\(\*\)\s*SI_UNIT\((\.[A-Z]+\.|\$)\s*,\s*\.METRE\.\)', mm)
    if um:
        unit = {b'.MILLI.': 1.0, b'$': 1000.0, b'.CENTI.': 10.0}.get(um.group(1), 1.0)
    if re.search(rb"CONVERSION_BASED_UNIT\s*\(\s*'INCH'", mm[:5_000_000]):
        unit = 25.4
    # ------------------------------------------------------------------ structure
    product = {i: (_strings(b) or [''])[0] for _, i, b in scan(mm, b'PRODUCT')}
    pdf = {}
    for typ in (b'PRODUCT_DEFINITION_FORMATION', b'PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE'):
        for _, i, b in scan(mm, typ):
            r = _refs(b); pdf[i] = r[0] if r else None
    pd = {}
    for _, i, b in scan(mm, b'PRODUCT_DEFINITION'):
        r = _refs(b); pd[i] = r[0] if r else None
    pds = {}; breaks = []
    for h, i, b in scan(mm, b'PRODUCT_DEFINITION_SHAPE'):
        r = _refs(b); pds[i] = r[0] if r else None; breaks.append(h)
    sdr = []
    for h, i, b in scan(mm, b'SHAPE_DEFINITION_REPRESENTATION'):
        r = _refs(b)
        if len(r) >= 2:
            sdr.append((r[0], r[1]))
        breaks.append(h)
    rep_items = {}
    for typ in REP_T:
        for h, i, b in scan(mm, typ):
            r = _refs(b)                       # ('name',(items),#context): items = all refs but the last
            rep_items[i] = r[:-1] if len(r) > 1 else r
            breaks.append(h)
    srr = []
    for h, i, b in scan(mm, b'SHAPE_REPRESENTATION_RELATIONSHIP'):
        r = _refs(b)
        if len(r) >= 2:
            srr.append((r[0], r[1]))
    rrwt = {}
    for m in re.finditer(rb'REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION\s*\(\s*#(\d+)', mm):
        s = m.start()
        h = mm.rfind(b'= (', max(0, s - 400), s)
        hh = mm.rfind(b'#', max(0, h - 24), h) if h >= 0 else -1
        if h < 0 or hh < 0:
            continue
        try:
            i = int(mm[hh + 1:h])
        except ValueError:
            continue
        rr = _refs(mm[h:s])
        if len(rr) >= 2:
            rrwt[i] = (rr[0], rr[1], int(m.group(1)))
    idt = {}
    for h, i, b in scan(mm, b'ITEM_DEFINED_TRANSFORMATION'):
        r = _refs(b)
        if len(r) >= 2:
            idt[i] = (r[0], r[1])
    cdsr = []
    for h, i, b in scan(mm, b'CONTEXT_DEPENDENT_SHAPE_REPRESENTATION'):
        r = _refs(b)
        if len(r) >= 2:
            cdsr.append((r[0], r[1]))
    nauo = {}
    for h, i, b in scan(mm, b'NEXT_ASSEMBLY_USAGE_OCCURRENCE'):
        r = _refs(b); ss = _strings(b)
        if len(r) >= 2:
            nauo[i] = (r[0], r[1], ss[1] if len(ss) > 1 else '')
    breaks += [h for h, _, _ in scan(mm, b'STYLED_ITEM', body=False)]
    t1 = time.time()
    # ------------------------------------------------------------------ solids, vertices, faces (ownership by offset)
    sol = []
    for typ in (b'MANIFOLD_SOLID_BREP', b'BREP_WITH_VOIDS', b'FACETED_BREP'):
        sol += [(h, i) for h, i, _ in scan(mm, typ, body=False)]
    sol.sort()
    S = len(sol)
    sol_off = np.array([h for h, _ in sol], np.int64); sol_ent = np.array([i for _, i in sol], np.int64)
    sol_of_ent = {int(i): k for k, i in enumerate(sol_ent)}
    bnd_off = np.r_[sol_off, np.array(sorted(breaks), np.int64)]
    bnd_sol = np.r_[np.arange(S), np.full(len(breaks), -1)]
    o = np.argsort(bnd_off, kind='stable'); bnd_off = bnd_off[o]; bnd_sol = bnd_sol[o]

    def owner(offs):
        if len(bnd_off) == 0 or len(offs) == 0:
            return np.full(len(offs), -1, np.int64)
        j = np.searchsorted(bnd_off, offs, side='right') - 1
        return np.where(j >= 0, bnd_sol[np.maximum(j, 0)], -1)

    vps = scan(mm, b'VERTEX_POINT')
    vp_off = np.array([h for h, _, _ in vps], np.int64)
    vp_pid = np.array([(_refs(b) or [0])[0] for _, _, b in vps], np.int64)
    del vps
    vp_sol = owner(vp_off)
    fcs = scan(mm, b'ADVANCED_FACE') + scan(mm, b'FACE_SURFACE')
    fcs.sort()
    f_off = np.array([h for h, _, _ in fcs], np.int64)
    f_sol = owner(f_off)
    f_surf = []; f_sense = []
    for _, _, b in fcs:
        r = _refs(b); f_surf.append(r[-1] if r else 0); f_sense.append(b'.F.' not in b[-12:])
    nfaces = len(fcs); del fcs
    seam_off = np.array([h for h, _, _ in scan(mm, b'SEAM_CURVE', body=False)], np.int64)

    def face_of(offs):
        """last face start before each offset, inside the same solid block"""
        if len(f_off) == 0 or len(offs) == 0:
            return np.full(len(offs), -1, np.int64)
        j = np.searchsorted(f_off, offs, side='right') - 1
        ok = j >= 0
        jb = np.searchsorted(bnd_off, offs, side='right') - 1
        fb = np.searchsorted(bnd_off, f_off[np.maximum(j, 0)], side='right') - 1
        return np.where(ok & (jb == fb), j, -1)
    seam_face = set(int(x) for x in face_of(seam_off) if x >= 0)
    vp_face = face_of(vp_off)
    cyl_surf = {}
    for typ, kind in ((b'CYLINDRICAL_SURFACE', 'cyl'), (b'CONICAL_SURFACE', 'cone')):
        for h, i, b in scan(mm, typ):
            r = _refs(b); fl = _floats(REF.sub(b'', STR_RE.sub(b'', b)))
            if r and fl:
                cyl_surf[i] = (r[0], fl[0], kind)
    cyl_faces = [(fi, int(f_sol[fi]), f_surf[fi], f_sense[fi]) + cyl_surf[f_surf[fi]]
                 for fi in range(nfaces) if f_sol[fi] >= 0 and f_surf[fi] in cyl_surf]
    t2 = time.time()
    # ------------------------------------------------------------------ needed axes / points / directions
    need_ax = {c[4] for c in cyl_faces}
    for a, b in idt.values():
        need_ax.add(a); need_ax.add(b)
    axes = {}
    if need_ax:
        for h, i, _ in scan(mm, b'AXIS2_PLACEMENT_3D', body=False):
            if i in need_ax:
                b = mm[h:ent_end(mm, h)]
                b = STR_RE.sub(b"''", b[b.find(b'('):])
                parts = b.split(b',')
                vals = []
                for p in parts[1:4]:
                    r = REF.search(p); vals.append(int(r.group(1)) if r else None)
                axes[i] = vals
    maxid = int(max([int(vp_pid.max()) if len(vp_pid) else 0] + [v[0] or 0 for v in axes.values()] + [0])) + 1
    pos_of = np.full(maxid + 1, -1, np.int64)
    pos_of[vp_pid] = np.arange(len(vp_pid))
    want_extra = np.zeros(maxid + 1, bool)
    cf_set = {c[0] for c in cyl_faces}
    face_pts = collections.defaultdict(list)
    for k in np.flatnonzero(vp_face >= 0):
        fi = int(vp_face[k])
        if fi in cf_set:
            face_pts[fi].append(int(vp_pid[k]))
    for v in axes.values():
        if v[0] and v[0] <= maxid:
            want_extra[v[0]] = True
    need_dir = {d for v in axes.values() for d in v[1:] if d}
    xyz = np.full((len(vp_pid), 3), np.nan)
    extra = {}
    for m in re.finditer(rb'= CARTESIAN_POINT\(', mm):
        s = m.start()
        hh = mm.rfind(b'#', max(0, s - 24), s)
        i = int(mm[hh + 1:s])
        if i > maxid:
            continue
        p = pos_of[i]
        if p < 0 and not want_extra[i]:
            continue
        a0 = mm.find(b'(', m.end())
        v = _floats(mm[a0:mm.find(b')', a0)])
        if len(v) < 3:
            continue
        if p >= 0:
            xyz[p] = v[:3]
        if want_extra[i]:
            extra[i] = v[:3]
    dirs = {}
    if need_dir:
        for m in re.finditer(rb'= DIRECTION\(', mm):
            s = m.start(); hh = mm.rfind(b'#', max(0, s - 24), s); i = int(mm[hh + 1:s])
            if i in need_dir:
                a0 = mm.find(b'(', m.end())
                dirs[i] = _floats(mm[a0:mm.find(b')', a0)])[:3]
    t3 = time.time()
    mm.close(); f.close()
    # ------------------------------------------------------------------ per-solid vertex statistics (vectorised)
    ok = (vp_sol >= 0) & ~np.isnan(xyz[:, 0])
    P = xyz[ok] * unit; sid = vp_sol[ok].astype(np.int64)
    o = np.argsort(sid, kind='stable'); P = P[o]; sid = sid[o]
    cnt = np.bincount(sid, minlength=S).astype(float)
    mean = np.zeros((S, 3)); bmin = np.full((S, 3), np.nan); bmax = np.full((S, 3), np.nan)
    V = np.tile(np.eye(3), (S, 1, 1)); ext = np.zeros((S, 3)); cen = np.full((S, 3), np.nan)
    if len(P):
        starts = np.r_[0, np.flatnonzero(np.diff(sid)) + 1]
        us = sid[starts]
        mean[us] = np.add.reduceat(P, starts, axis=0) / cnt[us][:, None]
        bmin[us] = np.minimum.reduceat(P, starts, axis=0); bmax[us] = np.maximum.reduceat(P, starts, axis=0)
        D = P - mean[sid]
        C = np.zeros((S, 3, 3))
        for a in range(3):
            for b in range(a, 3):
                v = np.add.reduceat(D[:, a] * D[:, b], starts) / cnt[us]
                C[us, a, b] = v; C[us, b, a] = v
        w, VV = np.linalg.eigh(C)
        V = VV[:, :, ::-1].copy()                      # columns: major, mid, minor
        Q = np.empty_like(D)
        for c0 in range(0, len(D), 1_000_000):
            sl = slice(c0, c0 + 1_000_000)
            Q[sl] = np.einsum('nij,ni->nj', V[sid[sl]], D[sl])
        qmin = np.minimum.reduceat(Q, starts, axis=0); qmax = np.maximum.reduceat(Q, starts, axis=0)
        ext[us] = qmax - qmin
        cen[us] = mean[us] + np.einsum('nij,nj->ni', V[us], (qmin + qmax) / 2)
    # ------------------------------------------------------------------ labels and placements
    rep_of_solid = np.full(S, -1, np.int64)
    for r, items in rep_items.items():
        for it in items:
            k = sol_of_ent.get(it)
            if k is not None:
                rep_of_solid[k] = r
    pd_of_rep = {}
    for p, r in sdr:
        d = pds.get(p)
        if d in pd:
            pd_of_rep[r] = d
    for _ in range(3):
        for a, b in srr:
            if a in pd_of_rep and b not in pd_of_rep:
                pd_of_rep[b] = pd_of_rep[a]
            elif b in pd_of_rep and a not in pd_of_rep:
                pd_of_rep[a] = pd_of_rep[b]
    name_of_pd = {d: product.get(pdf.get(pd.get(d)), '') for d in pd}

    def ax_matrix(a):
        v = axes.get(a)
        if not v:
            return np.eye(4)
        loc = np.array(extra.get(v[0], (0, 0, 0)), float) * unit
        return frame(loc, dirs.get(v[1]) if v[1] else None, dirs.get(v[2]) if v[2] else None)
    nauo_tf = {}
    pds_to_nauo = {p: d for p, d in pds.items() if d in nauo}
    for rel, p in cdsr:
        n = pds_to_nauo.get(p)
        if n is None or rel not in rrwt:
            continue
        t_ = rrwt[rel][2]
        if t_ in idt:
            a1, a2 = idt[t_]
            nauo_tf[n] = ax_matrix(a2) @ np.linalg.inv(ax_matrix(a1))
    children = collections.defaultdict(list); is_child = set()
    for n, (par, ch, nm) in nauo.items():
        children[par].append((n, ch)); is_child.add(ch)
    roots = [d for d in pd if d not in is_child]
    world = collections.defaultdict(list)
    stack = [(r, np.eye(4), name_of_pd.get(r, '')) for r in roots]
    guard = 0
    while stack and guard < 5_000_000:
        d, M, nm = stack.pop(); guard += 1
        world[d].append((M, nm))
        for n, ch in children.get(d, []):
            stack.append((ch, M @ nauo_tf.get(n, np.eye(4)), nauo[n][2] or name_of_pd.get(ch, '')))
    sol_label = []; inst = []
    for k in range(S):
        r = int(rep_of_solid[k])
        d = pd_of_rep.get(r) if r >= 0 else None
        sol_label.append(name_of_pd.get(d, '') if d is not None else '')
        for M, nm in (world.get(d) or [(np.eye(4), sol_label[-1])]):
            inst.append((k, M, nm or sol_label[-1]))
    cyl = []
    for (fi, si, sid_, sense, ax, rad, kind) in cyl_faces:
        v = axes.get(ax)
        if not v:
            continue
        loc = np.array(extra.get(v[0], (np.nan,) * 3), float) * unit
        dz = np.array(dirs.get(v[1], (0, 0, 1.0)) if v[1] else (0, 0, 1.0), float)
        dz /= np.linalg.norm(dz) or 1
        fp = np.array([xyz[pos_of[p]] for p in face_pts.get(fi, ()) if pos_of[p] >= 0], float).reshape(-1, 3) * unit
        cyl.append({'solid': si, 'r': rad * unit, 'p': loc, 'd': dz, 'concave': not sense, 'seam': fi in seam_face,
                    'kind': kind, 'fverts': fp})
    t4 = time.time()
    if log:
        log(f'{os.path.basename(path)}: {S} solids, {len(inst)} placed, {len(product)} products, {len(nauo)} NAUO, '
            f'{len(cyl)} cyl/cone faces, unit {unit} mm; struct {t1 - t0:.1f}s topo {t2 - t1:.1f}s coords {t3 - t2:.1f}s post {t4 - t3:.1f}s')
    return {'path': path, 'unit_mm': unit, 'n_products': len(product), 'n_nauo': len(nauo), 'solid_ent': sol_ent,
            'label': sol_label, 'inst': inst, 'nverts': cnt, 'mean': mean, 'bmin': bmin, 'bmax': bmax, 'axes': V,
            'ext': ext, 'center': cen, 'cyl': cyl}


LABEL = re.compile(r'^\s*(?P<mtype>[A-Za-z][A-Za-z _\-/]*?)\s*#\s*(?P<mno>\d+)\s*/\s*(?P<name>[^(\[]*?)\s*(?:\((?P<extra>[^()]*)\))?\s*(?:\[(?P<tag>approx|reference)[^\]]*\])?\s*$')
ROLLED = re.compile(r'^(W|S|M|HP|C|MC|L|2L|WT|MT|ST|HSS|TS|PIPE|P|ROUND|RD|RB|BAR|WS|WRF|DBL|Z|CEE|ZEE|T|UB|UC|PFC|SHS|RHS|CHS|EA|UA|HE|IPE|UPN)\d', re.I)
PLATE = re.compile(r'^(PL|BPL|FL|FLT|PLT|PLATE|GR|GT|GRTG|CHK|CP|SHIM|DECK|BENT|BP)', re.I)


def parse_label(s):
    """'BEAM #12 / W12x26 (piece 345, inst 1) [approx: ...]' -> dict(member_type, member, name, piece, inst, approx, kind)"""
    out = {'member_type': '', 'member': None, 'name': '', 'piece': None, 'inst': None, 'approx': '[approx' in s,
           'reference': '[reference' in s or 'reference part' in s, 'kind': 'other'}
    u = s.upper()
    if u.startswith('BOLT') or ' BOLT ' in u[:40]:
        out['kind'] = 'bolt'
    m = LABEL.match(s)
    if m:
        out['member_type'] = m.group('mtype').strip().upper(); out['member'] = int(m.group('mno')); out['name'] = m.group('name').strip()
        ex = m.group('extra') or ''
        pm = re.search(r'piece\s+(\d+)', ex); im = re.search(r'inst\s+(\d+)', ex)
        out['piece'] = int(pm.group(1)) if pm else None; out['inst'] = int(im.group(1)) if im else None
        if 'member envelope' in ex:
            out['kind'] = 'member_envelope'
        elif 'joist' in ex.lower() or 'joist stand-in' in s:
            out['kind'] = 'joist_standin'
    else:
        m2 = re.match(r'^\s*([^(\[]+?)\s*(?:\((?P<extra>[^()]*)\))?', s)
        if m2:
            out['name'] = m2.group(1).strip()
    n = (out['name'] or s).replace(' ', '')
    if out['kind'] == 'other':
        if out['reference']:
            out['kind'] = 'reference'
        elif ROLLED.match(n):
            out['kind'] = 'rolled'
        elif PLATE.match(n):
            out['kind'] = 'plate'
        elif 'concrete' in s.lower():
            out['kind'] = 'concrete'
    return out


def norm_section(s):
    s = (s or '').upper().replace(' ', '')
    s = re.sub(r'^TS', 'HSS', s)
    return s.replace('X', 'x')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('step')
    a = ap.parse_args()
    ix = index_step(a.step, log=print)
    kinds = collections.Counter(parse_label(l)['kind'] for _, _, l in ix['inst'])
    print('placed solids by kind:', dict(kinds))
    cc = [c for c in ix['cyl'] if c['concave']]
    print('cyl faces:', len(ix['cyl']), 'concave:', len(cc), 'concave with seam:', sum(c['seam'] for c in cc))


if __name__ == '__main__':
    main()
