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
    while i < len(L) and not BLOCK.match(L[i]):
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
def solid_holes(ix, s, cyls, kind):
    """concave cylinders of solid s -> list of holes {x, y, d, axis, slot_len} in the solid's PCA frame
    (x from the min end along the major axis, y from the min side along the mid axis)"""
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
        r = c['r']
        # same axis line as an existing group?
        hit = None
        for g in groups:
            if abs(g['r'] - r) > 0.05 or abs(abs(g['d'] @ d) - 1) > 1e-3:
                continue
            w = c['p'] - g['p']; w = w - g['d'] * (w @ g['d'])
            if np.linalg.norm(w) < 0.5:
                hit = g; break
        if hit is None:
            groups.append({'r': r, 'd': d, 'p': c['p'], 'n': 1, 'seam': c['seam']})
        else:
            hit['n'] += 1; hit['seam'] = hit['seam'] or c['seam']
    # pair the half-cylinders of slots: partial faces (no seam) with the same radius, parallel axes, axis lines
    # 0.5 mm .. 6 r apart, nearest first (the converter's own count treats such a pair as one hole)
    pairs = []
    for a in range(len(groups)):
        for b in range(a + 1, len(groups)):
            ga, gb = groups[a], groups[b]
            if ga['seam'] or gb['seam'] or abs(ga['r'] - gb['r']) > 0.05 or abs(abs(ga['d'] @ gb['d']) - 1) > 1e-3:
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
                      'slot_len': round(slot, 2), 'round': bool(g['seam'])})
    for dist, a, b in pairs:
        if a in used or b in used:
            continue
        used.add(a); used.add(b)
        ga, gb = groups[a], groups[b]
        pb = gb['p'] - ga['d'] * ((gb['p'] - ga['p']) @ ga['d'])
        put(ga, dist + 2 * ga['r'], (ga['p'] + pb) / 2)
    for a, g in enumerate(groups):
        if a not in used:
            put(g, 0.0, g['p'])
    return holes


def match_holes(nc, st, L, W, plate, pos_tol, dia_tol, dL=0.0):
    """best orientation: number of NC1 holes matched by a STEP hole (position + diameter); returns (matched, flip)"""
    best = (-1, None)
    if not nc or not st:
        return 0, None
    flips = [(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0)] if plate else [(1, 0, 0), (-1, 0, 0)]
    if not plate and abs(dL) > pos_tol:          # length differs: anchor at either end of the NC1 part
        flips += [(1, 0, dL), (-1, 0, dL)]
    for fx, fy, sh in flips:
        S = []
        for h in st:
            x = (h['x'] if fx > 0 else L - h['x']) - sh
            y = (h['y'] if fy > 0 else W - h['y']) if plate else 0.0
            S.append((x, y, h['d']))
        used = [False] * len(S); m = 0
        for hn in sorted(nc, key=lambda q: q['x']):
            for k, (x, y, d) in enumerate(S):
                if used[k] or abs(x - hn['x']) > pos_tol or abs(d - hn['d']) > dia_tol:
                    continue
                if plate and abs(y - hn['y']) > pos_tol:
                    continue
                used[k] = True; m += 1; break
        if m > best[0]:
            best = (m, (fx, fy, sh))
    return best


def step_pieces(ix):
    """unique solids with piece name, kind, length, width, placed-instance count and holes"""
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
                    'holes': solid_holes(ix, s, cyl_by.get(s, []), 'plate' if kind == 'plate' else 'rolled')})
    return out


def check(ix, parts, len_tol=3.0, pos_tol=2.0, dia_tol=0.6):
    pieces = step_pieces(ix)
    by_name = collections.defaultdict(list)
    for p in pieces:
        by_name[p['name']].append(p)
    rows = []
    for nc in parts:
        prof = norm_profile(nc['profile']); plate = nc['code'] == 'B' or prof.startswith('PL')
        Lr = nc['length'] or 0.0
        cands = []
        for p in by_name.get(prof, []):
            if plate:
                Wn = nc.get('width') or nc.get('height') or 0
                if abs(p['L'] - max(Lr, Wn)) <= len_tol and abs(p['W'] - min(Lr, Wn)) <= len_tol:
                    cands.append(p)
            elif abs(p['L'] - Lr) <= len_tol:
                cands.append(p)
        near = []
        loose = False
        if not cands and not plate and Lr:
            # same section, length within max(30 mm, 1 %): a revised part (different job state) - still compare holes
            cands = [p for p in by_name.get(prof, []) if abs(p['L'] - Lr) <= max(30.0, 0.01 * Lr)]
            loose = bool(cands)
        if not cands:
            near = sorted(by_name.get(prof, []), key=lambda p: abs(p['L'] - Lr))[:3]
        nh = len(nc['holes'])
        row = {'file': nc['file'], 'mark': nc['mark'], 'profile': nc['profile'], 'code': nc['code'], 'qty': nc['qty'], 'length': Lr,
               'nc1_holes': nh, 'nc1_marks': len(nc['marks']), 'nc1_slots': sum(1 for h in nc['holes'] if h['slot']),
               'nc1_diameters': dict(collections.Counter(round(h['d'], 2) for h in nc['holes'])),
               'candidates': len(cands), 'candidate_instances': sum(p['n_inst'] for p in cands)}
        if not cands:
            row['status'] = 'no_candidate'
            row['section_in_step'] = bool(by_name.get(prof))
            row['nearest_lengths'] = [round(p['L'], 1) for p in near]
            rows.append(row); continue
        scored = []
        for p in cands:
            Wd = p['W']
            m, flip = match_holes(nc['holes'], p['holes'], p['L'], Wd, plate, pos_tol, dia_tol, p['L'] - Lr)
            # also: STEP holes landing on NC1 marks (diameter 0: layout marks, e.g. anchor-rod holes torch-cut later)
            mk, _ = match_holes([dict(h, d=0.0) for h in nc['marks']], [dict(h, d=0.0) for h in p['holes']], p['L'], Wd, plate, pos_tol, 1e9) if nc['marks'] and p['holes'] else (0, None)
            scored.append((m, -abs(len(p['holes']) - nh), -abs(p['L'] - Lr), p, flip, mk))
        scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
        m, _, _, p, flip, mk = scored[0]
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
        row.update({'status': st, 'length_match': 'loose' if loose else 'strict', 'step_holes': sh, 'matched_holes': m, 'step_holes_on_nc1_marks': mk, 'step_label': p['label'],
                    'step_length': round(p['L'], 2), 'dL': round(p['L'] - Lr, 2), 'step_approx': p['approx'],
                    'step_diameters': dict(collections.Counter(h['d'] for h in p['holes'])),
                    'step_slots': sum(1 for h in p['holes'] if h['slot_len'] > 0),
                    'cand_hole_counts': sorted(collections.Counter(len(q['holes']) for q in cands).items())})
        if st not in ('exact', 'no_holes_both'):
            row['nc1_hole_x'] = sorted(round(h['x'], 1) for h in nc['holes'])[:40]
            fx, _, shf = flip or (1, 0, 0.0)
            row['step_hole_x'] = sorted(round((h['x'] if fx > 0 else p['L'] - h['x']) - shf, 1) for h in p['holes'])[:40]
        rows.append(row)
    return rows, pieces


def summarize(rows, pieces, manifest=None):
    st = collections.Counter(r['status'] for r in rows)

    def agg(sel):
        tot_nc = sum(r['nc1_holes'] for r in sel); tot_st = sum(r['step_holes'] for r in sel); tot_ok = sum(r['matched_holes'] for r in sel)
        return {'parts': len(sel), 'status': dict(collections.Counter(r['status'] for r in sel)), 'nc1_holes': tot_nc, 'step_holes': tot_st,
                'holes_matched_in_position': tot_ok, 'hole_recall': round(tot_ok / tot_nc, 4) if tot_nc else None,
                'hole_precision': round(tot_ok / tot_st, 4) if tot_st else None,
                'parts_with_nc1_holes': sum(1 for r in sel if r['nc1_holes']),
                'parts_missing_all_holes': sum(1 for r in sel if r['nc1_holes'] and r['step_holes'] == 0),
                'step_holes_on_nc1_marks': sum(r.get('step_holes_on_nc1_marks', 0) for r in sel)}
    strict = [r for r in rows if r.get('length_match') == 'strict']
    loose = [r for r in rows if r.get('length_match') == 'loose']
    geo_pieces_with_holes = sum(1 for p in pieces if p['holes'])
    geo_holes = sum(len(p['holes']) for p in pieces)
    out = {'nc1_parts': len(rows), 'nc1_parts_with_holes': sum(1 for r in rows if r['nc1_holes']), 'nc1_holes': sum(r['nc1_holes'] for r in rows),
           'nc1_marks': sum(r['nc1_marks'] for r in rows), 'status': dict(st),
           'length_strict': agg(strict), 'length_loose': agg(loose),
           'no_candidate': {'parts': st.get('no_candidate', 0),
                            'section_absent_in_step': sum(1 for r in rows if r['status'] == 'no_candidate' and not r.get('section_in_step')),
                            'section_present_length_differs': sum(1 for r in rows if r['status'] == 'no_candidate' and r.get('section_in_step'))},
           'step_unique_pieces': len(pieces), 'step_pieces_with_holes_geometric': geo_pieces_with_holes, 'step_holes_geometric': geo_holes,
           'step_round_holes_geometric': sum(1 for p in pieces for h in p['holes'] if h.get('round')),
           'step_slots_geometric': sum(1 for p in pieces for h in p['holes'] if h['slot_len'] > 0)}
    by_code = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        by_code[r['code'] or '?'][r['status']] += 1
        by_code[r['code'] or '?']['nc1_holes'] += r['nc1_holes']
        by_code[r['code'] or '?']['step_holes'] += r.get('step_holes', 0)
        by_code[r['code'] or '?']['matched'] += r.get('matched_holes', 0)
    out['by_profile_code'] = {k: dict(v) for k, v in by_code.items()}
    if manifest:
        out['manifest_holes'] = manifest.get('holes')
        out['manifest_counts'] = {k: manifest.get('counts', {}).get(k) for k in ('pieces_written', 'pieces_exact', 'pieces_approx', 'placed_pieces')}
        sk = {}
        for g in (manifest.get('standins') or {}).get('groups', []):
            if g.get('type') == 'holes_not_cut':
                sk[g.get('real_type')] = g.get('count')
        out['manifest_holes_not_cut'] = sk
    return out


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
    rows, pieces = check(ix, parts, a.len_tol, a.pos_tol, a.dia_tol)
    summ = summarize(rows, pieces, man)
    summ.update({'job': a.job, 'label': a.label, 'step': a.step, 'nc1_source': a.nc1, 'sec': round(time.time() - t0, 1),
                 'tolerances_mm': {'length': a.len_tol, 'position': a.pos_tol, 'diameter': a.dia_tol}})
    json.dump({'summary': summ, 'rows': rows}, open(a.out, 'w'), indent=1, default=str)
    print(json.dumps(summ, indent=1, default=str))
    if a.md:
        L = [f"# NC1 hole check: {a.job} ({a.label})", '', '```', json.dumps(summ, indent=1, default=str), '```', '',
             '| file | mark | profile | L | NC1 holes | STEP holes | matched | status | dL | STEP label |', '|---|---|---|---|---|---|---|---|---|---|']
        for r in rows:
            L.append(f"| {r['file'].split('/')[-1]} | {r['mark']} | {r['profile']} | {r['length']} | {r['nc1_holes']} | {r.get('step_holes', '')} | "
                     f"{r.get('matched_holes', '')} | {r['status']} | {r.get('dL', '')} | {r.get('step_label', '')[:60]} |")
        open(a.md, 'w').write('\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
