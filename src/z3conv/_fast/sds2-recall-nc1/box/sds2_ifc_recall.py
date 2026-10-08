#!/usr/bin/env python3
"""SDS2 STEP vs the job's own IFC export: alignment, then recall / precision per type.

Reference = an IFC that SDS2 exported from the same job (e.g. 50_Binney_Job.ifc: IfcBeam / IfcColumn per member main
material with Name = piece mark and ObjectType = section, IfcDiscreteAccessory / IfcBuildingElementProxy for
connection material and plates). Candidate = the converter's STEP (indexed by stepidx: every placed solid with its
label 'BEAM #12 / W12x26 (piece 345, inst 1)', PCA box and world placement).

1. Units: STEP in mm (LENGTH_UNIT read from the file), IFC geometry converted to mm (ifcopenshell, declared unit).
2. Registration (STEP job coordinates -> IFC coordinates, which may be georeferenced): rotation about Z voted from the
   plan directions of long members with the same section on both sides, translation voted from their PCA-box centres,
   refined by least squares (2-D Kabsch + Z offset) on the inlier pairs. No scale is fitted (units are explicit).
3. Matching: every STEP solid is paired one-to-one (greedy, nearest first) with an IFC product whose PCA-box centre
   lies within --tol mm after registration and whose extents agree (major within max(15 mm, 3 %), the other two within
   max(10 mm, 25 %)).
4. Report: IFC recall per IFC class / SDS2 role (ObjectType), STEP precision per STEP kind (member main material,
   other rolled, plate, bolt, joist stand-in, envelope, reference part), section-name agreement on matched pairs, and
   the unmatched groups (what is missing / extra) with examples.
usage: python sds2_ifc_recall.py --step X.step --ifc Y.ifc|Y.npz [--label v5.1] [--job NAME] -o out.json [--md out.md]
"""
import os, sys, re, json, time, argparse, collections, pickle, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stepidx

MEMBER_T = ('BEAM', 'COLUMN', 'VERTICAL BRACE', 'HORIZONTAL BRACE', 'BRACE', 'GIRT', 'PURLIN', 'JOIST', 'MISC', 'STAIR', 'RAIL', 'EMBED')


def norm_sec(s):
    s = (s or '').upper().replace(' ', '').replace('*', '')
    s = re.sub(r'^TS', 'HSS', s)
    return s.replace('X', 'x')


def step_instances(ix):
    """placed STEP solids in world coordinates + parsed labels"""
    out = {'center': [], 'ext': [], 'axes': [], 'label': [], 'kind': [], 'name': [], 'mtype': [], 'member': [], 'solid': [], 'approx': []}
    for k, M, lab in ix['inst']:
        if not np.isfinite(ix['center'][k]).all() or ix['nverts'][k] < 2:
            continue
        R = M[:3, :3]; t = M[:3, 3]
        pl = stepidx.parse_label(lab)
        out['center'].append(R @ ix['center'][k] + t); out['ext'].append(ix['ext'][k]); out['axes'].append(R @ ix['axes'][k])
        out.setdefault('nv', []).append(int(ix['nverts'][k]))
        out['label'].append(lab); out['name'].append(norm_sec(pl['name'])); out['mtype'].append(pl['member_type'])
        out['member'].append(pl['member']); out['solid'].append(k); out['approx'].append(pl['approx'])
        out['kind'].append(pl['kind'])
    for key in ('center', 'ext'):
        out[key] = np.array(out[key]).reshape(-1, 3)
    out['axes'] = np.array(out['axes']).reshape(-1, 3, 3)
    # main material of a member: rolled piece whose section equals the most common rolled section of that member
    by_m = collections.defaultdict(list)
    for i, (m, kd) in enumerate(zip(out['member'], out['kind'])):
        if m is not None and kd == 'rolled':
            by_m[m].append(i)
    main = np.zeros(len(out['label']), bool)
    for m, idx in by_m.items():
        L = np.array([out['ext'][i][0] for i in idx])
        main[idx[int(np.argmax(L))]] = True               # the longest rolled piece of the member = its main material
    out['main'] = main
    cls = []
    for i in range(len(out['label'])):
        kd = out['kind'][i]
        if kd == 'rolled':
            cls.append('member_main' if main[i] and out['mtype'][i] not in ('MISC',) else 'rolled_other')
        else:
            cls.append(kd)
    out['cls'] = cls
    return out


SEC_RE = re.compile(r'^(W|S|M|HP|C|MC|L|2L|WT|MT|ST|HSS|TS|PIPE|P|ROUND|RD|RB|BAR|WS|Z|T|UB|UC|PFC|SHS|RHS|CHS|EA|UA|HE|IPE|UPN|PL|FL|BPL|GT|GR)\d', re.I)


def ifc_section(row):
    """section / plate size of an IFC product: SDS2 writes it in Description (ObjectType = role, Name = piece mark)"""
    for v in (row[4], row[3]):
        v = (v or '').replace(' ', '')
        if v and SEC_RE.match(v):
            return norm_sec(v)
    return ''


def ifc_role(row):
    """IFC class, for SDS2 exports split by ObjectType (MATERIAL / CONNECTION MATERIAL / BOLT ...) and plate vs section"""
    c = row[1]; ot = (row[3] or '').upper().strip(); ds = (row[4] or '').upper().strip()
    if c in ('IfcBeam', 'IfcColumn', 'IfcMember'):
        return c
    if c in ('IfcDiscreteAccessory', 'IfcBuildingElementProxy', 'IfcPlate', 'IfcMechanicalFastener', 'IfcFastener'):
        sec = ifc_section(row)
        kind = 'plate' if (ds.startswith('PLATE') or sec.startswith('PL') or sec.startswith('FL') or c == 'IfcPlate') else (
            'bolt' if ('BOLT' in ds or 'BOLT' in ot or c in ('IfcMechanicalFastener', 'IfcFastener')) else ('section' if sec else (ds[:14] or '?')))
        return f'{c}:{ot[:22] or "?"}:{kind}'
    return c


def rot_z(th):
    c, s = math.cos(th), math.sin(th)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def ext_pairs(S, F, rng, max_n=4000):
    """(STEP, IFC) index pairs of long items (> 1.5 m) whose PCA extents agree (major within max(15 mm, 1 %), mid within
    max(10 mm, 10 %), minor within max(10 mm, 25 %)) - correspondence candidates for the translation vote"""
    si = np.flatnonzero(S['ext'][:, 0] > 1500); fi = np.flatnonzero(F['ext'][:, 0] > 1500)
    if len(si) > max_n: si = rng.choice(si, max_n, replace=False)
    if len(fi) > max_n: fi = rng.choice(fi, max_n, replace=False)
    if not len(si) or not len(fi):
        return []
    o = np.argsort(F['ext'][fi, 0]); fi = fi[o]; Lf = F['ext'][fi, 0]
    out = []
    for i in si:
        es = S['ext'][i]; tol = max(15.0, 0.01 * es[0])
        a = np.searchsorted(Lf, es[0] - tol); b = np.searchsorted(Lf, es[0] + tol)
        if b <= a:
            continue
        J = fi[a:b]; E = F['ext'][J]
        ok = (np.abs(E[:, 1] - es[1]) <= np.maximum(10, 0.1 * E[:, 1])) & (np.abs(E[:, 2] - es[2]) <= np.maximum(10, 0.25 * E[:, 2]))
        out += [(int(i), int(j)) for j in J[ok][:200]]
    return out


def register(S, F, log=print):
    """vote rotation about Z and translation from same-section long members; returns (R, t, info)"""
    fsec = [ifc_section(r) for r in F['rows']]
    fidx = collections.defaultdict(list)
    for i, s in enumerate(fsec):
        if F['ext'][i][0] > 1500:
            fidx[s].append(i)
    pairs = []
    rng = np.random.default_rng(0)
    sidx = collections.defaultdict(list)
    for i, s in enumerate(S['name']):
        if S['cls'][i] in ('member_main', 'rolled_other') and S['ext'][i][0] > 1500:
            sidx[s].append(i)
    for sec, si in sidx.items():
        fi = fidx.get(sec)
        if not fi:
            continue
        si = np.array(si); fi = np.array(fi)
        if len(si) > 400: si = rng.choice(si, 400, replace=False)
        if len(fi) > 400: fi = rng.choice(fi, 400, replace=False)
        Ls = S['ext'][si, 0]; Lf = F['ext'][fi, 0]
        ok = np.abs(Ls[:, None] - Lf[None, :]) <= np.maximum(15, 0.01 * Lf[None, :])
        a, b = np.nonzero(ok)
        for x, y in zip(si[a], fi[b]):
            pairs.append((x, y))
    how = 'section+length'
    if len(pairs) < 20:
        # no usable section names (or a non-SDS2 IFC): pair long items whose three PCA extents agree
        pairs += ext_pairs(S, F, rng)
        how = 'extents' if pairs else how
    if not pairs:
        return None, None, {'pairs': 0, 'reason': 'no section/length or extent correspondences between STEP and IFC'}
    if len(pairs) > 300000:
        pairs = [pairs[k] for k in rng.choice(len(pairs), 300000, replace=False)]
    pairs = np.array(pairs)
    # rotation votes from horizontal-ish member directions (mod 180 deg)
    ds = S['axes'][pairs[:, 0], :, 0]; df = F['axes'][pairs[:, 1], :, 0]
    hz = (np.abs(ds[:, 2]) < 0.3) & (np.abs(df[:, 2]) < 0.3)
    th_votes = (np.arctan2(df[hz, 1], df[hz, 0]) - np.arctan2(ds[hz, 1], ds[hz, 0])) % np.pi
    cands = [0.0]
    if len(th_votes):
        h, edges = np.histogram(th_votes, bins=720, range=(0, np.pi))
        for j in np.argsort(h)[::-1][:4]:
            cands.append((edges[j] + edges[j + 1]) / 2)
    best = None
    for th0 in cands:
        for th in (th0, th0 + np.pi):
            R = rot_z(th)
            d = F['center'][pairs[:, 1]] - S['center'][pairs[:, 0]] @ R.T
            q = np.round(d / 50.0).astype(np.int64)
            keys, cnt = np.unique(q, axis=0, return_counts=True)
            j = int(np.argmax(cnt))
            sel = np.all(q == keys[j], axis=1)
            t = np.median(d[sel], axis=0)
            score = int(cnt[j])
            if best is None or score > best[0]:
                best = (score, th, t, sel)
    score, th, t, sel = best
    # refine: inlier pairs (unique per STEP solid) -> 2-D Kabsch + z offset, two rounds
    R = rot_z(th)
    for _ in range(3):
        d = F['center'][pairs[:, 1]] - (S['center'][pairs[:, 0]] @ R.T + t)
        inl = np.linalg.norm(d, axis=1) < 40.0
        if inl.sum() < 3:
            break
        P = S['center'][pairs[inl, 0]]; Q = F['center'][pairs[inl, 1]]
        pc = P[:, :2].mean(0); qc = Q[:, :2].mean(0)
        H = (P[:, :2] - pc).T @ (Q[:, :2] - qc)
        U, _, Vt = np.linalg.svd(H)
        R2 = Vt.T @ U.T
        if np.linalg.det(R2) < 0:
            Vt[1] *= -1; R2 = Vt.T @ U.T
        R = np.eye(3); R[:2, :2] = R2
        t = np.r_[qc - R2 @ pc, np.median(Q[:, 2] - P[:, 2])]
    d = F['center'][pairs[:, 1]] - (S['center'][pairs[:, 0]] @ R.T + t)
    inl = np.linalg.norm(d, axis=1) < 40.0
    info = {'pairs': int(len(pairs)), 'pairing': how, 'vote_peak': score, 'rotation_deg': round(math.degrees(math.atan2(R[1, 0], R[0, 0])), 4),
            'translation_mm': [round(float(x), 2) for x in t], 'inlier_pairs': int(inl.sum()),
            'inlier_rms_mm': round(float(np.sqrt((np.linalg.norm(d[inl], axis=1) ** 2).mean())), 3) if inl.any() else None}
    log(f"registration: {info}")
    return R, t, info


def extents_ok(es, ef, sparse=False):
    a = abs(es[0] - ef[0]) <= max(15.0, 0.03 * ef[0])
    if sparse:          # few B-rep vertices (round bars / tubes: vertices only on seams): the cross-section box is not measurable
        return a
    if not a:
        return False
    # square-ish cross-sections (square HSS, square bars, symmetric built-ups): the two minor PCA axes are degenerate, so
    # the box can be rotated by any angle in the section plane (extents up to sqrt(2) x the side): compare rotation-tolerantly
    if abs(es[1] - es[2]) <= 0.2 * max(es[1], 1.0) or abs(ef[1] - ef[2]) <= 0.2 * max(ef[1], 1.0):
        return (max(es[1], es[2]) <= 1.45 * max(ef[1], ef[2]) + 10 and max(ef[1], ef[2]) <= 1.45 * max(es[1], es[2]) + 10
                and min(es[1], es[2]) >= 0.65 * min(ef[1], ef[2]) - 10 and min(ef[1], ef[2]) >= 0.65 * min(es[1], es[2]) - 10)
    b = abs(es[1] - ef[1]) <= max(10.0, 0.25 * ef[1])
    c = abs(es[2] - ef[2]) <= max(10.0, 0.25 * ef[2])
    return a and b and c


def ball_query(A, Bc, r):
    """for every row of A the indices of the rows of Bc within distance r (uniform grid hash, cell = r)"""
    grid = collections.defaultdict(list)
    for j, k in enumerate(map(tuple, np.floor(Bc / r).astype(np.int64))):
        grid[k].append(j)
    offs = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)]
    out = []
    for i, k in enumerate(map(tuple, np.floor(A / r).astype(np.int64))):
        c = []
        for dx, dy, dz in offs:
            c += grid.get((k[0] + dx, k[1] + dy, k[2] + dz), ())
        if c:
            c = np.array(c); d = np.linalg.norm(Bc[c] - A[i], axis=1)
            out.append(c[d <= r].tolist())
        else:
            out.append([])
    return out


def match(S, F, R, t, tol):
    Cs = S['center'] @ R.T + t
    cand = []
    ok = np.isfinite(Cs).all(1)
    nbs = ball_query(np.where(ok[:, None], Cs, 1e18), F['center'], tol)
    for i, nb in enumerate(nbs):
        for j in nb:
            if extents_ok(S['ext'][i], F['ext'][j], S['nv'][i] <= 24 or S['ext'][i][1] < 0.3 * F['ext'][j][1]):
                cand.append((float(np.linalg.norm(Cs[i] - F['center'][j])), i, j))
    cand.sort()
    ms = {}; mf = {}
    for d, i, j in cand:
        if i in ms or j in mf:
            continue
        ms[i] = (j, d); mf[j] = (i, d)
    return ms, mf, Cs


NONPHYS = ('IfcOpeningElement', 'IfcSpace', 'IfcAnnotation', 'IfcGrid', 'IfcVirtualElement', 'IfcSite', 'IfcBuilding',
           'IfcBuildingStorey', 'IfcDistributionPort')


def physical_only(F):
    """drop IFC products that are not physical parts (openings / voids, spaces, annotations, grids)"""
    keep = [i for i, r in enumerate(F['rows']) if r[1] not in NONPHYS]
    exc = dict(collections.Counter(r[1] for r in F['rows'] if r[1] in NONPHYS))
    if len(keep) == len(F['rows']):
        return F, exc
    G = dict(F)
    G['rows'] = [F['rows'][i] for i in keep]
    for k in ('center', 'ext', 'axes', 'bmin', 'bmax', 'nverts'):
        G[k] = F[k][keep]
    return G, exc


def is_weld(row):
    return 'WELD' in (row[3] or '').upper() or 'WELD' in (row[4] or '').upper() or row[1] == 'IfcFastener' and 'WELD' in (row[2] or '').upper()


def is_bolt_role(ro):
    return ro.endswith(':bolt')


JOIST_RE = re.compile(r'^\d+(K|LH|DLH|KCS|G|BG|VG|SLH)\d', re.I)


def bolt_containment(S, F, Cs, roles, margin=10.0, fsel=None, scls=('bolt',)):
    """bolts are written as several solids (bolt, nut, washers) in the STEP and as one product in the IFC (likewise a
    joist stand-in = chords + web bars): an IFC product is recalled when a STEP solid of that kind has its centre inside
    the product's bbox (+margin); such a STEP solid counts as matched"""
    fb = [j for j, ro in enumerate(roles) if (fsel(j) if fsel else is_bolt_role(ro))]
    sb = [i for i, c in enumerate(S['cls']) if c in scls]
    if not fb or not sb:
        return set(), set()
    lo = F['bmin'][fb] - margin; hi = F['bmax'][fb] + margin
    cen = (lo + hi) / 2; rad = float(np.max(np.linalg.norm(hi - lo, axis=1) / 2))
    P = Cs[sb]
    nb = ball_query(cen, P, max(rad, 1.0))
    fh = set(); sh = set()
    for k, idx in enumerate(nb):
        if not idx:
            continue
        idx = np.array(idx)
        inside = np.all((P[idx] >= lo[k]) & (P[idx] <= hi[k]), axis=1)
        if inside.any():
            fh.add(fb[k]); sh.update(sb[i] for i in idx[inside])
    return fh, sh


def run(step, ifc, tol=25.0, label='', job='', log=print, index_cache=None, ifc_cache=None):
    t0 = time.time()
    if index_cache and os.path.exists(index_cache):
        ix = pickle.load(open(index_cache, 'rb'))
    else:
        ix = stepidx.index_step(step, log=log)
        if index_cache:
            pickle.dump(ix, open(index_cache, 'wb'))
    import ifc_products
    if ifc.endswith('.npz'):
        F = ifc_products.load(ifc)
    elif ifc_cache and os.path.exists(ifc_cache):
        F = ifc_products.load(ifc_cache)
    else:
        F = ifc_products.digest(ifc, log=log)
        if ifc_cache:
            ifc_products.save(F, ifc_cache)
    S = step_instances(ix)
    F, excluded = physical_only(F)
    log(f'STEP placed solids {len(S["label"])}; IFC products {len(F["rows"])} (excluded {excluded})')
    R, t, reg = register(S, F, log)
    res = {'job': job, 'label': label, 'step': step, 'ifc': F['meta'], 'registration': reg, 'tol_mm': tol,
           'step_solids': len(S['label']), 'ifc_products': len(F['rows']), 'ifc_excluded_non_physical': excluded}
    if not len(S['label']) or not len(F['rows']):
        res['status'] = 'empty_side'
        return res
    # candidates: the voted registration and the identity (SDS2 IFC exports normally keep the job coordinates);
    # the one with more one-to-one matches wins
    cands = ([('voted', R, t)] if R is not None else []) + [('identity', np.eye(3), np.zeros(3))]
    best = None
    for nm, R_, t_ in cands:
        ms_, mf_, Cs_ = match(S, F, R_, t_, tol)
        reg[f'matches_{nm}'] = len(ms_)
        if best is None or len(ms_) > len(best[1]):
            best = (nm, ms_, mf_, Cs_, R_, t_)
    nm, ms, mf, Cs, R, t = best
    reg['used'] = nm
    # also a loose pass (3x tol) to tell "nearby but different extents / offset" from "absent"
    msl, mfl, _ = match(S, F, R, t, 3 * tol)
    roles = [ifc_role(r) for r in F['rows']]
    weld = [is_weld(r) for r in F['rows']]
    roles = [('weld (not modelled in STEP):' + ro) if w else ro for ro, w in zip(roles, weld)]
    fsec = [ifc_section(r) for r in F['rows']]
    fh, sh = bolt_containment(S, F, Cs, roles)
    jh, jsh = bolt_containment(S, F, Cs, roles, 25.0, fsel=lambda j: bool(JOIST_RE.match((F['rows'][j][4] or F['rows'][j][3] or '').replace(' ', ''))) and j not in mf,
                               scls=('joist_standin',))
    mF = set(mf) | fh | jh; mS = set(ms) | sh | jsh
    # STEP solids inside the IFC's coverage (its products' bbox + 0.5 m): the IFC may be one sequence of the job
    flo = F['bmin'].min(0) - 500.0; fhi = F['bmax'].max(0) + 500.0
    in_cov = np.all((Cs >= flo) & (Cs <= fhi), axis=1) if len(Cs) else np.zeros(0, bool)
    rec = collections.defaultdict(lambda: [0, 0, 0])
    for j, ro in enumerate(roles):
        rec[ro][0] += 1
        if j in mF:
            rec[ro][1] += 1
        elif j in mfl:
            rec[ro][2] += 1
    prec = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for i, c in enumerate(S['cls']):
        prec[c][0] += 1
        if i in mS:
            prec[c][1] += 1
        elif i in msl:
            prec[c][2] += 1
        if in_cov[i]:
            prec[c][3] += 1
            if i in mS:
                prec[c][4] += 1
    sec_eq = collections.Counter()
    for i, (j, d) in ms.items():
        if S['cls'][i] in ('member_main', 'rolled_other', 'plate'):
            fs = fsec[j]; ss = S['name'][i]
            sec_eq['same' if fs and fs == ss else ('ifc_generic' if fs in ('PLATE', '') else 'different')] += 1
    dists = np.array([d for (j, d) in ms.values()]) if ms else np.zeros(0)
    nphys = sum(1 for w in weld if not w)
    nm_phys = sum(1 for j in mF if not weld[j])
    ncov = int(in_cov.sum()); nmcov = sum(1 for i in mS if in_cov[i])
    res.update({
        'status': 'ok',
        'recall_by_ifc_role': {k: {'n': v[0], 'matched': v[1], 'recall': round(v[1] / v[0], 4) if v[0] else None, 'near_only_3tol': v[2]}
                               for k, v in sorted(rec.items(), key=lambda kv: -kv[1][0])},
        'precision_by_step_kind': {k: {'n': v[0], 'matched': v[1], 'precision': round(v[1] / v[0], 4) if v[0] else None, 'near_only_3tol': v[2],
                                       'n_in_ifc_coverage': v[3], 'precision_in_ifc_coverage': round(v[4] / v[3], 4) if v[3] else None}
                                   for k, v in sorted(prec.items(), key=lambda kv: -kv[1][0])},
        'overall': {'ifc_recall': round(len(mF) / len(F['rows']), 4) if F['rows'] else None,
                    'ifc_recall_excl_welds': round(nm_phys / nphys, 4) if nphys else None, 'ifc_products_excl_welds': nphys,
                    'step_precision': round(len(mS) / len(S['label']), 4) if S['label'] else None,
                    'step_precision_in_ifc_coverage': round(nmcov / ncov, 4) if ncov else None, 'step_solids_in_ifc_coverage': ncov,
                    'matched_pairs': len(ms), 'bolts_by_containment': [len(fh), len(sh)], 'joists_by_containment': [len(jh), len(jsh)],
                    'match_dist_mm_median': round(float(np.median(dists)), 2) if len(dists) else None,
                    'match_dist_mm_p95': round(float(np.percentile(dists, 95)), 2) if len(dists) else None},
        'section_agreement_on_matched': dict(sec_eq),
    })
    # unmatched groups with examples
    um_f = collections.Counter(); ex_f = collections.defaultdict(list)
    for j, r in enumerate(F['rows']):
        if j not in mF:
            key = (roles[j], fsec[j])
            um_f[key] += 1
            if len(ex_f[key]) < 3:
                ex_f[key].append({'name': r[2], 'guid': r[0], 'center': [round(float(x)) for x in F['center'][j]], 'ext': [round(float(x)) for x in F['ext'][j]],
                                  'near_step': ' '.join(S['label'][mfl[j][0]].split()[:6]) if j in mfl else None})
    um_s = collections.Counter(); ex_s = collections.defaultdict(list)
    Cs_ = Cs
    for i in range(len(S['label'])):
        if i not in mS:
            key = (S['cls'][i], S['name'][i] if S['cls'][i] != 'bolt' else 'BOLT')
            um_s[key] += 1
            if len(ex_s[key]) < 3:
                ex_s[key].append({'label': S['label'][i][:110], 'center_in_ifc_frame': [round(float(x)) for x in Cs_[i]], 'ext': [round(float(x)) for x in S['ext'][i]]})
    res['unmatched_ifc_top'] = [{'role': k[0], 'section': k[1], 'n': n, 'examples': ex_f[k]} for k, n in um_f.most_common(25)]
    res['unmatched_step_top'] = [{'cls': k[0], 'section': k[1], 'n': n, 'examples': ex_s[k]} for k, n in um_s.most_common(25)]
    # bbox overlap (are both models covering the same area?)
    if len(Cs):
        smin, smax = Cs.min(0), Cs.max(0); fmin, fmax = F['center'].min(0), F['center'].max(0)
        lo = np.maximum(smin, fmin); hi = np.minimum(smax, fmax)
        inter = np.prod(np.clip(hi - lo, 0, None)[:2]); a1 = np.prod((smax - smin)[:2]); a2 = np.prod((fmax - fmin)[:2])
        res['plan_overlap'] = {'step_bbox_mm': [[round(float(x)) for x in smin], [round(float(x)) for x in smax]],
                               'ifc_bbox_mm': [[round(float(x)) for x in fmin], [round(float(x)) for x in fmax]],
                               'intersection_over_step': round(float(inter / a1), 3) if a1 else None,
                               'intersection_over_ifc': round(float(inter / a2), 3) if a2 else None}
    res['sec'] = round(time.time() - t0, 1)
    return res


def to_md(res):
    L = [f"# IFC recall: {res.get('job')} ({res.get('label')})", '',
         f"- STEP: `{res.get('step')}`", f"- IFC: `{res['ifc'].get('path')}` ({res['ifc'].get('origin')}, {res['ifc'].get('schema')}, units {res['ifc'].get('units')})",
         f"- registration: {res.get('registration')}", f"- overall: {res.get('overall')}", f"- plan overlap: {res.get('plan_overlap')}",
         f"- section agreement on matched: {res.get('section_agreement_on_matched')}", '', '## IFC recall by role', '',
         '| IFC role | n | matched | recall | near only (3x tol) |', '|---|---|---|---|---|']
    for k, v in (res.get('recall_by_ifc_role') or {}).items():
        L.append(f"| {k} | {v['n']} | {v['matched']} | {v['recall']} | {v['near_only_3tol']} |")
    L += ['', '## STEP precision by kind', '', '| STEP kind | n | matched | precision | near only (3x tol) |', '|---|---|---|---|---|']
    for k, v in (res.get('precision_by_step_kind') or {}).items():
        L.append(f"| {k} | {v['n']} | {v['matched']} | {v['precision']} | {v['near_only_3tol']} |")
    L += ['', '## Unmatched IFC groups (top)', '']
    for g in res.get('unmatched_ifc_top', [])[:15]:
        L.append(f"- {g['role']} {g['section']}: {g['n']}  e.g. {g['examples'][:1]}")
    L += ['', '## Unmatched STEP groups (top)', '']
    for g in res.get('unmatched_step_top', [])[:15]:
        L.append(f"- {g['cls']} {g['section']}: {g['n']}  e.g. {g['examples'][:1]}")
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--step', required=True); ap.add_argument('--ifc', required=True)
    ap.add_argument('--label', default=''); ap.add_argument('--job', default=''); ap.add_argument('--tol', type=float, default=25.0)
    ap.add_argument('--index-cache'); ap.add_argument('--ifc-cache')
    ap.add_argument('-o', '--out', required=True); ap.add_argument('--md')
    a = ap.parse_args()
    res = run(a.step, a.ifc, a.tol, a.label, a.job, index_cache=a.index_cache, ifc_cache=a.ifc_cache)
    json.dump(res, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps({k: res.get(k) for k in ('status', 'registration', 'overall', 'recall_by_ifc_role', 'precision_by_step_kind', 'section_agreement_on_matched', 'plan_overlap')}, indent=1, default=str))
    if a.md:
        open(a.md, 'w').write(to_md(res))


if __name__ == '__main__':
    main()
