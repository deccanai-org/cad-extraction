#!/usr/bin/env python3
"""NC1 / DSTV hole check for SDS2 -> STEP outputs.

Ground truth = the job's own NC1 (DSTV) files written by SDS2: one file per fabricated part with its piece mark, profile,
cut length and the BO blocks (one line per hole: face, x along the part, y on the face, diameter, depth; slots carry
extra fields). Lines with diameter 0 are layout marks (centre punches), not holes; they are counted separately.

STEP side = the converter's STEP read with stepidx (no B-rep build): every unique solid with its piece name (STEP
product / NAUO label, e.g. 'BEAM #1 / W21x62 (piece 1855, inst 1)'), PCA frame and length, and its holes found
geometrically: concave cylindrical faces whose axis crosses the part (rolled: axis not parallel to the length; plates:
axis along the thickness), grouped by axis line (one hole = one axis), half-cylinders of one slot merged.
Optionally the v5/v5.1 sidecar <name>_stage2_manifest.json ('holes': pieces with holes / holes) is read and compared
with the geometric total (validates the detector against the converter's own count).

Matching NC1 part -> STEP piece: same section (normalised: W18X40 == W18x40, TS == HSS, 'PL1 1/2X18' == 'PL1 1/2x18')
and |length difference| <= --len-tol mm (plates: length and width); among the candidates the one whose holes match the
NC1 holes best (x along the part within --pos-tol, diameter within --dia-tol, both part directions tried; plates: 2-D,
4 flips) is scored. Every NC1 part gets one of:
  exact          hole count equal and every hole matched in position and diameter
  count_equal    same count, some positions / diameters differ
  missing_holes  STEP piece has fewer holes (incl. none) than the NC1 part
  extra_holes    STEP piece has more holes than the NC1 part
  no_holes_both  neither has holes (matched part, nothing to compare)
  no_candidate   no STEP solid with that section and length (piece absent or different job revision)
usage: python nc1_holes_check.py --step X_stage2.step --nc1 <dir|zip> [--manifest X_stage2_manifest.json]
                                 [--label v5.1] [--job NAME] -o out.json [--md out.md]
"""
import os, sys, re, io, json, glob, zipfile, argparse, collections, time, pickle
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stepidx

BLOCK = re.compile(r'^\s*([A-Z]{2})\s*$')
NUM = re.compile(r'^([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)([a-z]*)$')


def parse_nc1(text, name=''):
    """DSTV NC1 -> dict(mark, profile, code, qty, length, width, thick, holes=[...], marks=[...])"""
    L = text.replace('\r', '').split('\n')
    i = 0
    while i < len(L) and L[i].strip() != 'ST':
        i += 1
    hdr = []
    i += 1
    # header: order, drawing, phase, mark, grade, qty, profile, code, length, height, flange w, flange t, web t, ...
    # (2-letter profile codes RO / RU / SO must not end it: a block line only counts after the length field)
    while i < len(L) and not (BLOCK.match(L[i]) and len(hdr) >= 9):
        s = L[i].strip()
        if s.startswith('**'):
            i += 1; continue
        hdr.append(s); i += 1

    def h(k, conv=str, default=None):
        try:
            return conv(hdr[k])
        except (IndexError, ValueError):
            return default
    part = {'file': name, 'order': h(0), 'drawing': h(1), 'phase': h(2), 'mark': h(3), 'grade': h(4), 'qty': h(5, lambda x: int(float(x)), 1),
            'profile': h(6, str, ''), 'code': h(7, str, ''), 'length': h(8, float), 'height': h(9, float), 'flange_w': h(10, float),
            'flange_t': h(11, float), 'web_t': h(12, float), 'holes': [], 'marks': [], 'blocks': collections.Counter()}
    cur = None
    for line in L[i:]:
        m = BLOCK.match(line)
        if m:
            cur = m.group(1); part['blocks'][cur] += 1
            continue
        if cur != 'BO' or not line.strip():
            continue
        tok = line.split()
        if len(tok) < 4:
            continue
        face = tok[0] if tok[0].isalpha() else 'v'
        vals = tok[1:] if tok[0].isalpha() else tok
        nums = []
        for t in vals:
            mm = NUM.match(t)
            if mm:
                nums.append((float(mm.group(1)), mm.group(2)))
        if len(nums) < 3:
            continue
        x, y, d = nums[0][0], nums[1][0], nums[2][0]
        depth = nums[3][0] if len(nums) > 3 else 0.0
        slot = None
        if len(nums) >= 7 or (len(nums) > 3 and 'l' in nums[3][1]):
            # slot: d, depth + 'l', slot length, slot width, angle
            try:
                slot = {'len': nums[4][0], 'width': nums[5][0], 'angle': nums[6][0] if len(nums) > 6 else 0.0}
            except IndexError:
                slot = None
        rec = {'face': face, 'x': x, 'y': y, 'd': d, 'depth': depth, 'x_ref': nums[0][1], 'y_ref': nums[1][1], 'slot': slot}
        (part['holes'] if d > 0 else part['marks']).append(rec)
    part['blocks'] = dict(part['blocks'])
    if part['code'] == 'B':          # plate: length, width, thickness
        part['width'] = part['height']; part['thick'] = part['web_t']
    return part


def read_nc1_source(src):
    """dir (recursive) or zip -> list of parsed parts"""
    out = []
    if os.path.isdir(src):
        for f in sorted(glob.glob(os.path.join(src, '**', '*'), recursive=True)):
            if f.lower().endswith('.nc1') and os.path.isfile(f):
                out.append(parse_nc1(open(f, errors='replace').read(), os.path.relpath(f, src)))
    elif zipfile.is_zipfile(src):
        z = zipfile.ZipFile(src)
        for n in sorted(z.namelist()):
            if n.lower().endswith('.nc1'):
                out.append(parse_nc1(z.read(n).decode('latin-1'), n))
    return out


def norm_profile(p):
    p = (p or '').upper().replace(' ', '')
    p = re.sub(r'^TS', 'HSS', p)
    p = p.replace('X', 'x')
    return p


# ------------------------------------------------------------------------------------------------ STEP holes
def solid_holes(ix, s, cyls, kind, diag=None):
    """concave cylinder faces of solid s -> holes {x, y, d, axis, slot_len, round} in the solid's PCA frame
    (x from the min end along the major axis, y from the min side along the mid axis).
    One hole = the faces on one axis line with the same radius and overlapping axial intervals whose angular coverage
    is a full circle (a seam face, or two half faces). Two half-cylinders on parallel axis lines 0.5 mm .. 6 r apart =
    one slot. Partial arcs (cope / fillet radii) and unpaired half-cylinders are not holes (counted in diag)."""
    E = ix['axes'][s]; c0 = ix['center'][s]; ext = ix['ext'][s]
    e1, e2, e3 = E[:, 0], E[:, 1], E[:, 2]
    groups = []
    for c in cyls:
        if not c['concave'] or c['kind'] != 'cyl' or not np.isfinite(c['p']).all():
            continue
        d = c['d']
        if kind == 'plate':
            if abs(d @ e3) < 0.9:
                continue
        else:
            if abs(d @ e1) > 0.5:          # along the part: fillet / tube bore, not a hole
                continue
        r = c['r']; t0, t1 = c.get('t0'), c.get('t1')
        hit = None
        for g in groups:
            if abs(g['r'] - r) > 0.05 or abs(abs(g['d'] @ d) - 1) > 1e-3:
                continue
            w = c['p'] - g['p']; off = float(w @ g['d']); w = w - g['d'] * off
            if np.linalg.norm(w) >= 0.5:
                continue
            if t0 is not None and g['t0'] is not None:
                sg = 1.0 if (d @ g['d']) > 0 else -1.0
                a, b = sorted((off + sg * t0, off + sg * t1))
                if a > g['t1'] + 0.5 or b < g['t0'] - 0.5:
                    continue
                g['t0'] = min(g['t0'], a); g['t1'] = max(g['t1'], b)
            hit = g; break
        span = c.get('span')
        if hit is None:
            groups.append({'r': r, 'd': d, 'p': c['p'], 'n': 1, 'seam': c['seam'], 'cov': span if span is not None else -1.0,
                           't0': t0, 't1': t1})
        else:
            hit['n'] += 1; hit['seam'] = hit['seam'] or c['seam']
            hit['cov'] = (hit['cov'] if hit['cov'] >= 0 else 0) + (span if span is not None else 0)
    full = []; half = []; arcs = 0
    for g in groups:
        cov = 360.0 if g['seam'] else g['cov']
        if cov >= 340 or (cov < 0 and g['n'] >= 2):
            full.append(g)
        elif 170 <= cov <= 190 or cov < 0:
            half.append(g)
        else:
            arcs += 1
    pairs = []
    for a in range(len(half)):
        for b in range(a + 1, len(half)):
            ga, gb = half[a], half[b]
            if abs(ga['r'] - gb['r']) > 0.05 or abs(abs(ga['d'] @ gb['d']) - 1) > 1e-3:
                continue
            w = gb['p'] - ga['p']; w = w - ga['d'] * (w @ ga['d']); dist = float(np.linalg.norm(w))
            if 0.5 < dist <= 6 * ga['r']:
                pairs.append((dist, a, b))
    pairs.sort()
    used = set(); holes = []

    def put(g, slot, p):
        q = p - c0
        holes.append({'x': float(q @ e1 + ext[0] / 2), 'y': float(q @ e2 + ext[1] / 2), 'd': round(2 * g['r'], 3),
                      'axis': 'e3' if abs(g['d'] @ e3) > 0.7 else ('e2' if abs(g['d'] @ e2) > 0.7 else 'oblique'),
                      'slot_len': round(slot, 2), 'round': slot == 0.0})
    for dist, a, b in pairs:
        if a in used or b in used:
            continue
        used.add(a); used.add(b)
        ga, gb = half[a], half[b]
        pb = gb['p'] - ga['d'] * ((gb['p'] - ga['p']) @ ga['d'])
        put(ga, dist + 2 * ga['r'], (ga['p'] + pb) / 2)
    for g in full:
        put(g, 0.0, g['p'])
    if diag is not None:
        diag['arcs'] += arcs
        diag['half_unpaired'] += len(half) - len(used)
    return holes


def nc1_points(h):
    """reference points of an NC1 hole: the BO point, and for a slot also the slot centre (point + elongation/2 along
    the slot angle; DSTV gives the elongation between the arc centres)"""
    pts = [(h['x'], h['y'])]
    sl = h.get('slot')
    if sl and sl.get('len'):
        a = np.radians(sl.get('angle') or 0.0)
        pts.append((h['x'] + 0.5 * sl['len'] * np.cos(a), h['y'] + 0.5 * sl['len'] * np.sin(a)))
    return pts


def _assign(A, B, pos_tol, dia_tol):
    """one-to-one nearest-first matching of 2-D points with diameters: A = [(pts, d)], B = [(x, y, d)] -> count"""
    cand = []
    for a, (pts, dn) in enumerate(A):
        for kk, (x, y, d) in enumerate(B):
            if abs(d - dn) > dia_tol:
                continue
            dist = min(max(abs(x - px), abs(y - py)) for px, py in pts)
            if dist <= pos_tol:
                cand.append((dist, a, kk))
    cand.sort()
    ua = set(); us = set(); m = 0
    for dist, a, kk in cand:
        if a in ua or kk in us:
            continue
        ua.add(a); us.add(kk); m += 1
    return m


def plate_rigid(nc, st, pos_tol, dia_tol, max_holes=40):
    """plates: best 2-D rigid fit (rotation + translation, optionally mirrored; no scale) of the NC1 hole pattern onto
    the STEP holes, hypothesised from hole pairs with equal spacing and diameter. Independent of the plate's PCA frame,
    which is ambiguous for square-ish or clipped plates. Returns matched count."""
    if len(nc) < 2 or len(st) < 2 or len(nc) > max_holes or len(st) > max_holes:
        return 0
    S = np.array([(h['x'], h['y']) for h in st]); Sd = [h['d'] for h in st]
    best = 0
    for mirror in (1.0, -1.0):
        N = np.array([(h['x'], mirror * h['y']) for h in nc]); Nd = [h['d'] for h in nc]
        prs = sorted(((float(np.hypot(*(N[i] - N[j]))), i, j) for i in range(len(N)) for j in range(i + 1, len(N))), reverse=True)[:4]
        seen = set()
        for dn, i, j in prs:
            vn = N[j] - N[i]
            for a in range(len(S)):
                if abs(Sd[a] - Nd[i]) > dia_tol:
                    continue
                for b in range(len(S)):
                    if a == b or abs(Sd[b] - Nd[j]) > dia_tol:
                        continue
                    vs = S[b] - S[a]
                    if abs(float(np.hypot(*vs)) - dn) > pos_tol:
                        continue
                    th = np.arctan2(vs[1], vs[0]) - np.arctan2(vn[1], vn[0])
                    c, s_ = np.cos(th), np.sin(th)
                    R = np.array([[c, -s_], [s_, c]]); t = S[a] - R @ N[i]
                    key = (round(float(th), 2), round(float(t[0])), round(float(t[1])))
                    if key in seen:
                        continue
                    seen.add(key)
                    T = N @ R.T + t
                    m = _assign([([(float(x), float(y))], d) for (x, y), d in zip(T, Nd)], [(float(x), float(y), d) for (x, y), d in zip(S, Sd)], pos_tol, dia_tol)
                    best = max(best, m)
                    if best == len(nc):
                        return best
    return best


def match_holes(nc, st, L, W, plate, pos_tol, dia_tol, dL=0.0, swap=False):
    """best orientation: number of NC1 holes matched one-to-one by a STEP hole (position along the part, on plates
    also across, and diameter); returns (matched, flip). swap: plate whose NC1 'length' is its shorter side (NC1 x runs
    along the STEP piece's mid axis)"""
    best = (-1, None)
    if not nc or not st:
        return 0, None
    flips = [(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0)] if plate else [(1, 0, 0), (-1, 0, 0)]
    if not plate and abs(dL) > pos_tol:          # length differs: anchor at either end of the NC1 part
        flips += [(1, 0, dL), (-1, 0, dL)]
    ncp = [([(py, px) for px, py in nc1_points(h)] if swap else nc1_points(h), h['d']) for h in sorted(nc, key=lambda q: q['x'])]
    for fx, fy, sh in flips:
        S = []
        for h in st:
            x = (h['x'] if fx > 0 else L - h['x']) - sh
            y = (h['y'] if fy > 0 else W - h['y']) if plate else 0.0
            S.append((x, y, h['d']))
        # all (NC1 hole, STEP hole) pairs within tolerance, assigned one-to-one nearest first
        cand = []
        for a, (pts, dn) in enumerate(ncp):
            for kk, (x, y, d) in enumerate(S):
                if abs(d - dn) > dia_tol:
                    continue
                dist = min(max(abs(x - px), abs(y - py) if plate else 0.0) for px, py in pts)
                if dist <= pos_tol:
                    cand.append((dist, a, kk))
        cand.sort()
        ua = set(); us = set(); m = 0
        for dist, a, kk in cand:
            if a in ua or kk in us:
                continue
            ua.add(a); us.add(kk); m += 1
        if m > best[0]:
            best = (m, (fx, fy, sh))
    if plate and best[0] < len(nc):
        mr = plate_rigid(nc, st, pos_tol, dia_tol)
        if mr > best[0]:
            best = (mr, ('rigid', 0, 0))
    return best


def step_pieces(ix, diag=None):
    """unique solids with piece name, kind, length, width, placed-instance count and holes"""
    if diag is None:
        diag = collections.Counter()
    cyl_by = collections.defaultdict(list)
    for c in ix['cyl']:
        cyl_by[c['solid']].append(c)
    inst_lab = collections.defaultdict(list)
    for k, M, lab in ix['inst']:
        inst_lab[k].append(lab)
    out = []
    for s in range(len(ix['label'])):
        labs = inst_lab.get(s) or [ix['label'][s]]
        pl = stepidx.parse_label(labs[0] if stepidx.parse_label(labs[0])['name'] else ix['label'][s])
        if not pl['name']:
            pl = stepidx.parse_label(ix['label'][s])
        kind = pl['kind']
        if kind in ('bolt', 'joist_standin', 'member_envelope', 'concrete', 'reference'):
            continue
        name = norm_profile(pl['name'])
        ext = ix['ext'][s]
        out.append({'solid': s, 'name': name, 'kind': kind, 'label': labs[0][:120], 'n_inst': len(labs), 'L': float(ext[0]), 'W': float(ext[1]),
                    'T': float(ext[2]), 'approx': pl['approx'], 'members': sorted({stepidx.parse_label(l)['member'] for l in labs if stepidx.parse_label(l)['member'] is not None})[:20],
                    'holes': solid_holes(ix, s, cyl_by.get(s, []), 'plate' if kind == 'plate' else 'rolled', diag)})
    return out


def check(ix, parts, len_tol=3.0, pos_tol=2.0, dia_tol=0.6):
    diag = collections.Counter()
    pieces = step_pieces(ix, diag)
    by_name = collections.defaultdict(list)
    for p in pieces:
        by_name[p['name']].append(p)
    rows = []
    for nc in parts:
        prof = norm_profile(nc['profile']); plate = nc['code'] == 'B' or prof.startswith('PL') or prof.startswith('FL')
        Lr = nc['length'] or 0.0
        Wn = (nc.get('width') or nc.get('height') or 0.0) if plate else 0.0
        cands = []
        for p in by_name.get(prof, []):
            if plate:
                if abs(p['L'] - max(Lr, Wn)) <= len_tol and abs(p['W'] - min(Lr, Wn)) <= len_tol:
                    cands.append(p)
            elif abs(p['L'] - Lr) <= len_tol:
                cands.append(p)
        loose = False
        if not cands and Lr >= 1500:
            # main-member length (>= 1.5 m) within max(30 mm, 0.25 %): a revised part (different job state) - holes still compared;
            # short parts (clips, plates) must match within --len-tol (a loose match there compares a different piece)
            tol = max(30.0, 0.0025 * Lr)
            if plate:
                cands = [p for p in by_name.get(prof, []) if abs(p['L'] - max(Lr, Wn)) <= tol and abs(p['W'] - min(Lr, Wn)) <= max(len_tol, 0.02 * min(Lr, Wn) + 3)]
            else:
                cands = [p for p in by_name.get(prof, []) if abs(p['L'] - Lr) <= tol]
            loose = bool(cands)
        nh = len(nc['holes'])
        row = {'file': nc['file'], 'sha256': nc.get('sha256'), 'mark': nc['mark'], 'profile': nc['profile'], 'code': nc['code'], 'qty': nc['qty'],
               'length': Lr, 'width': Wn or None, 'nc1_holes': nh, 'nc1_marks': len(nc['marks']), 'nc1_slots': sum(1 for h in nc['holes'] if h['slot']),
               'nc1_diameters': dict(collections.Counter(round(h['d'], 2) for h in nc['holes'])),
               'candidates': len(cands), 'candidate_instances': sum(p['n_inst'] for p in cands)}
        if not cands:
            near = sorted(by_name.get(prof, []), key=lambda p: abs(p['L'] - (max(Lr, Wn) if plate else Lr)))[:3]
            row['status'] = 'no_candidate'
            row['section_in_step'] = bool(by_name.get(prof))
            row['nearest_lengths'] = [round(p['L'], 1) for p in near]
            rows.append(row); continue
        scored = []
        swap = bool(plate and Wn and Lr < Wn)
        for p in cands:
            m, flip = match_holes(nc['holes'], p['holes'], p['L'], p['W'], plate, pos_tol, dia_tol, p['L'] - (max(Lr, Wn) if plate else Lr), swap)
            scored.append((m, -abs(len(p['holes']) - nh), -abs(p['L'] - (max(Lr, Wn) if plate else Lr)), p, flip))
        scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        m, _, _, p, flip = scored[0]
        sh = len(p['holes'])
        if nh == 0 and sh == 0:
            st = 'no_holes_both'
        elif sh == nh and m == nh:
            st = 'exact'
        elif sh == nh:
            st = 'count_equal'
        elif sh < nh:
            st = 'missing_holes'
        else:
            st = 'extra_holes'
        mk = 0
        if nc['marks'] and p['holes']:
            mk, _ = match_holes([dict(h, d=0.0) for h in nc['marks']], [dict(h, d=0.0) for h in p['holes']], p['L'], p['W'], plate, pos_tol, 1e9, 0.0, swap)
        # strongest evidence of holes missing in the STEP: same section, length within --len-tol, NC1 lists holes and no
        # candidate STEP piece has any hole
        row['strict_zero'] = bool(not loose and nh > 0 and all(len(q['holes']) == 0 for q in cands))
        row.update({'status': st, 'length_match': 'loose' if loose else 'strict', 'step_holes': sh, 'matched_holes': m,
                    'step_holes_on_nc1_marks': mk, 'step_label': p['label'], 'step_kind': p['kind'],
                    'step_length': round(p['L'], 2), 'dL': round(p['L'] - (max(Lr, Wn) if plate else Lr), 2), 'step_approx': p['approx'],
                    'step_diameters': dict(collections.Counter(h['d'] for h in p['holes'])),
                    'step_slots': sum(1 for h in p['holes'] if h['slot_len'] > 0),
                    'cand_hole_counts': sorted(collections.Counter(len(q['holes']) for q in cands).items())})
        if st not in ('exact', 'no_holes_both'):
            row['nc1_hole_x'] = sorted(round(h['x'], 1) for h in nc['holes'])[:40]
            fx, _, shf = flip if (flip and flip[0] != 'rigid') else (1, 0, 0.0)
            row['step_hole_x'] = sorted(round((h['x'] if fx > 0 else p['L'] - h['x']) - shf, 1) for h in p['holes'])[:40]
            row['match_frame'] = 'rigid_fit' if (flip and flip[0] == 'rigid') else 'pca'
            if plate:
                row['nc1_hole_xy'] = [(round(h['x'], 1), round(h['y'], 1)) for h in nc['holes']][:20]
                row['step_hole_xy'] = [(round(h['x'], 1), round(h['y'], 1)) for h in p['holes']][:20]
                row['step_WL'] = [round(p['L'], 1), round(p['W'], 1)]
            dn = collections.Counter(round(h['d'], 1) for h in nc['holes']); ds = collections.Counter(round(h['d'], 1) for h in p['holes'])
            row['diameter_mismatch'] = bool(nh and sh and not (set(dn) & set(ds)))
        rows.append(row)
    return rows, pieces, diag


def role(code, profile):
    p = norm_profile(profile)
    if code == 'B' or p.startswith('PL') or p.startswith('FL'):
        return 'plate'
    if code == 'L' or p.startswith('L'):
        return 'angle'
    return 'rolled_main'


def agg(sel):
    tot_nc = sum(r['nc1_holes'] for r in sel); tot_st = sum(r.get('step_holes', 0) for r in sel); tot_ok = sum(r.get('matched_holes', 0) for r in sel)
    return {'parts': len(sel), 'status': dict(collections.Counter(r['status'] for r in sel)), 'nc1_holes': tot_nc, 'step_holes': tot_st,
            'holes_matched_in_position': tot_ok, 'hole_recall': round(tot_ok / tot_nc, 4) if tot_nc else None,
            'hole_precision': round(tot_ok / tot_st, 4) if tot_st else None,
            'parts_with_nc1_holes': sum(1 for r in sel if r['nc1_holes']),
            'parts_missing_all_holes': sum(1 for r in sel if r['nc1_holes'] and r.get('step_holes', 0) == 0),
            'parts_all_holes_matched': sum(1 for r in sel if r['nc1_holes'] and r.get('matched_holes', 0) == r['nc1_holes']),
            'diameter_mismatch_parts': sum(1 for r in sel if r.get('diameter_mismatch')),
            'step_holes_on_nc1_marks': sum(r.get('step_holes_on_nc1_marks', 0) for r in sel)}


STATUS_RANK = {'exact': 6, 'no_holes_both': 5, 'count_equal': 4, 'extra_holes': 3, 'missing_holes': 2, 'no_candidate': 0}


def summarize(rows, pieces, diag=None, manifest=None):
    st = collections.Counter(r['status'] for r in rows)
    matched = [r for r in rows if r['status'] != 'no_candidate']
    # one row per piece mark: the revision whose STEP comparison is best (the job state matches one revision)
    best = {}
    for r in rows:
        k = (r['mark'] or r['file']).upper()
        if k not in best or (STATUS_RANK[r['status']], r.get('matched_holes', 0)) > (STATUS_RANK[best[k]['status']], best[k].get('matched_holes', 0)):
            best[k] = r
    bm = list(best.values())
    out = {'nc1_parts': len(rows), 'nc1_marks_distinct': len(bm), 'nc1_parts_with_holes': sum(1 for r in rows if r['nc1_holes']),
           'nc1_holes': sum(r['nc1_holes'] for r in rows), 'nc1_punch_marks': sum(r['nc1_marks'] for r in rows),
           'nc1_slots': sum(r['nc1_slots'] for r in rows), 'status': dict(st),
           'matched_parts': agg(matched), 'by_mark_best': agg([r for r in bm if r['status'] != 'no_candidate']),
           'length_strict': agg([r for r in rows if r.get('length_match') == 'strict']),
           'length_loose': agg([r for r in rows if r.get('length_match') == 'loose']),
           'by_role': {ro: agg([r for r in matched if role(r['code'], r['profile']) == ro]) for ro in ('rolled_main', 'angle', 'plate')},
           'step_approx_matched': agg([r for r in matched if r.get('step_approx')]),
           'strict_zero': {'parts': sum(1 for r in rows if r.get('strict_zero')), 'nc1_holes': sum(r['nc1_holes'] for r in rows if r.get('strict_zero')),
                           'by_role': dict(collections.Counter(role(r['code'], r['profile']) for r in rows if r.get('strict_zero'))),
                           'approx_pieces': sum(1 for r in rows if r.get('strict_zero') and r.get('step_approx')),
                           'examples': [{k: r.get(k) for k in ('mark', 'profile', 'length', 'nc1_holes', 'nc1_diameters', 'step_label', 'candidates', 'file')}
                                        for r in sorted((r for r in rows if r.get('strict_zero')), key=lambda r: -r['nc1_holes'])[:12]]},
           'step_hole_density': round(sum(len(p['holes']) for p in pieces) / len(pieces), 3) if pieces else None,
           'no_candidate': {'parts': st.get('no_candidate', 0),
                            'section_absent_in_step': sum(1 for r in rows if r['status'] == 'no_candidate' and not r.get('section_in_step')),
                            'section_present_length_differs': sum(1 for r in rows if r['status'] == 'no_candidate' and r.get('section_in_step'))},
           'match_rate_parts': round(len(matched) / len(rows), 4) if rows else None,
           'step_unique_pieces': len(pieces), 'step_pieces_with_holes_geometric': sum(1 for p in pieces if p['holes']),
           'step_holes_geometric': sum(len(p['holes']) for p in pieces),
           'step_round_holes_geometric': sum(1 for p in pieces for h in p['holes'] if h.get('round')),
           'step_slots_geometric': sum(1 for p in pieces for h in p['holes'] if h['slot_len'] > 0),
           'step_holes_by_kind': dict(collections.Counter(p['kind'] for p in pieces for h in p['holes'])),
           'step_non_hole_arcs': dict(diag or {})}
    by_code = collections.defaultdict(collections.Counter)
    for r in rows:
        c = by_code[r['code'] or '?']
        c[r['status']] += 1; c['nc1_holes'] += r['nc1_holes']; c['step_holes'] += r.get('step_holes', 0); c['matched'] += r.get('matched_holes', 0)
    out['by_profile_code'] = {k: dict(v) for k, v in by_code.items()}
    if manifest:
        out['manifest_holes'] = manifest.get('holes')
        out['manifest_counts'] = {k: (manifest.get('counts') or {}).get(k) for k in ('pieces_written', 'pieces_exact', 'pieces_approx', 'placed_pieces', 'unique_parts')}
        sk = {}
        for g in (manifest.get('standins') or {}).get('groups', []):
            if g.get('type') == 'holes_not_cut':
                sk[g.get('real_type')] = g.get('count')
        out['manifest_holes_not_cut'] = sk
        out['manifest_class'] = [manifest.get('class'), manifest.get('corpus'), manifest.get('class_reasons')]
    return out


def to_md(summ, rows, title):
    L = [f"# NC1 hole check: {title}", '', '```', json.dumps(summ, indent=1, default=str), '```', '',
         '| file | mark | profile | L | NC1 holes | STEP holes | matched | status | dL | STEP label |', '|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        L.append(f"| {r['file'].split('/')[-1]} | {r['mark']} | {r['profile']} | {r['length']} | {r['nc1_holes']} | {r.get('step_holes', '')} | "
                 f"{r.get('matched_holes', '')} | {r['status']} | {r.get('dL', '')} | {r.get('step_label', '')[:60]} |")
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--step', required=True); ap.add_argument('--nc1', required=True); ap.add_argument('--manifest')
    ap.add_argument('--label', default=''); ap.add_argument('--job', default='')
    ap.add_argument('--len-tol', type=float, default=3.0); ap.add_argument('--pos-tol', type=float, default=2.0)
    ap.add_argument('--dia-tol', type=float, default=0.6); ap.add_argument('--index-cache')
    ap.add_argument('-o', '--out', required=True); ap.add_argument('--md')
    a = ap.parse_args()
    t0 = time.time()
    parts = read_nc1_source(a.nc1)
    if a.index_cache and os.path.exists(a.index_cache):
        ix = pickle.load(open(a.index_cache, 'rb'))
    else:
        ix = stepidx.index_step(a.step, log=print)
        if a.index_cache:
            pickle.dump(ix, open(a.index_cache, 'wb'))
    man = json.load(open(a.manifest)) if a.manifest and os.path.exists(a.manifest) else None
    rows, pieces, diag = check(ix, parts, a.len_tol, a.pos_tol, a.dia_tol)
    summ = summarize(rows, pieces, diag, man)
    summ.update({'job': a.job, 'label': a.label, 'step': a.step, 'nc1_source': a.nc1, 'sec': round(time.time() - t0, 1),
                 'tolerances_mm': {'length': a.len_tol, 'position': a.pos_tol, 'diameter': a.dia_tol}})
    json.dump({'summary': summ, 'rows': rows}, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps(summ, indent=1, default=str))
    if a.md:
        open(a.md, 'w').write(to_md(summ, rows, f'{a.job} ({a.label})'))


if __name__ == '__main__':
    main()
