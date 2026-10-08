"""steelstd unit tests: tables against the standards' own size formulas, every builder built with build123d (valid
closed solids, exact volume and box vs the analytic target, determinism), and every op of the standards patches built
and checked against its target and against the baseline part it replaces.

    python3 tests/test_steelstd.py            # (needs build123d 0.13.0; run on Modal: modal_test.py)
"""
import json
import math
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
STD = os.path.dirname(HERE)
sys.path.insert(0, STD)
from steelstd import geom as G, tables as T, fasteners as FA, members as ME, joists as JO, grating as GR  # noqa: E402

IN = T.IN
RESULTS = []


def check(name, cond, detail=''):
    RESULTS.append({'test': name, 'ok': bool(cond), 'detail': detail})
    if not cond:
        print('FAIL', name, detail)


def valid(s):
    v = s.is_valid
    return bool(v() if callable(v) else v)


def shape_ok(g, name, vol_tol=1e-6, bbox_tol=0.02):
    """build the GEOM, check every solid valid + closed, the volume and the bounding box against the analytic target"""
    from build123d import Compound
    sh = G.to_shape(g)
    solids = sh.solids() if hasattr(sh, 'solids') else [sh]
    check(f'{name}: solid count', len(solids) == G.n_solids(g), f'{len(solids)} vs {G.n_solids(g)}')
    check(f'{name}: valid', all(valid(s) for s in solids))
    vol = sum(s.volume for s in solids)
    tv = G.volume(g)
    if 'cuts' in json.dumps(g):
        tv = None
    if tv is not None:
        check(f'{name}: volume', abs(vol - tv) <= vol_tol * max(tv, 1.0) + 1e-3, f'built {vol:.4f} vs exact {tv:.4f}')
    bb = Compound(children=solids).bounding_box() if len(solids) > 1 else solids[0].bounding_box()
    tb = G.bbox(g) if 'sweep' not in json.dumps(g) else None
    if tb:
        got = [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]
        err = max(abs(a - b) for a, b in zip(got, tb))
        check(f'{name}: bbox', err <= bbox_tol, f'max dev {err:.4f} mm')
    return vol


# ------------------------------------------------------------------ tables vs the standards' formulas
def test_tables():
    for d, (F, H) in T.HEAVY_HEX_NUT.items():
        if d >= 0.5 or d in (0.25, 0.375):          # 5/16 and 7/16 are off the formula in B18.2.2 (9/16, 3/4)
            check(f'heavy hex nut {d}: F = 1.5D + 1/8', abs(F - (1.5 * d + 0.125)) < 1e-9, f'{F}')
        Hf = d - 1 / 64 if d <= 1.125 else d - 1 / 32
        check(f'heavy hex nut {d}: H = D - 1/64 (<= 1 1/8) / D - 1/32 (1 1/4 - 1 1/2)', abs(H - Hf) < 1e-9, f'{H}')
    for d, (F, H, thr) in T.HEAVY_HEX_BOLT.items():
        check(f'heavy hex bolt {d}: F = nut F', abs(F - T.HEAVY_HEX_NUT[d][0]) < 1e-9)
        check(f'heavy hex bolt {d}: H < nut H', H < T.HEAVY_HEX_NUT[d][1])
    for d, (F, H) in T.HEX_BOLT.items():
        if d >= 0.5 or d == 0.375:                  # 1/4, 5/16, 7/16 hex bolts are off 1.5 D in B18.2.1
            check(f'hex bolt {d}: F = 1.5 D', abs(F - 1.5 * d) < 1e-9, f'{F}')
    for d, (std, ovs, ss, ls) in T.HOLES_J3_3.items():
        check(f'J3.3 {d}: standard = d + 1/16', abs(std - (d + 1 / 16)) < 1e-9)
        check(f'J3.3 {d}: slot widths = standard', ss[0] == std and ls[0] == std)
    for d, (ID, OD, tmin, tmax) in T.F436_WASHER.items():
        check(f'F436 {d}: ID > D, OD > ID, tmin < tmax', ID > d and OD > ID and tmin < tmax)
        if d in T.HEAVY_HEX_NUT and d >= 0.5:
            check(f'F436 {d}: OD >= nut across flats', OD >= T.HEAVY_HEX_NUT[d][0] - 1e-9)
    for n, (db, A, w) in T.REBAR_A615.items():
        check(f'A615 #{n}: area = pi db^2 / 4', abs(A - math.pi * db * db / 4) < 0.006 * max(A, 1), f'{A}')
        check(f'A615 #{n}: weight = 3.4 pi db^2 / 4', abs(w - 3.4 * math.pi * db * db / 4) < 0.005 * w,
              f'{w} vs {3.4 * math.pi * db * db / 4:.3f}')
        if n <= 8:
            check(f'A615 #{n}: dia = n/8', abs(db - n / 8) < 1e-9)
    # RCSC rule on known AISC examples: 3/4 grip 1 1/2 -> 2 1/2; 7/8 grip 2 1/8 + 2 washers -> 3 3/4
    check('RCSC 3/4 grip 1.5', FA.bolt_length(0.75, 1.5)[0] == 2.5)
    check('RCSC 7/8 grip 2.125 2 washers', FA.bolt_length(0.875, 2.125, 2)[0] == 3.75, FA.bolt_length(0.875, 2.125, 2))
    check('RCSC rounds by 1/2 above 5 in', FA.bolt_length(1.0, 4.5)[0] == 6.0, FA.bolt_length(1.0, 4.5))
    check('bolt family A325N', FA.bolt_family('A325N') == 'heavy_hex')
    check('bolt family F3125', FA.bolt_family('ASTM F3125 A490X') == 'heavy_hex')
    check('bolt family A307', FA.bolt_family('A307') == 'hex')
    check('bolt family HILTI unknown', FA.bolt_family('HILTI_HASM') is None)
    check('HSS parse', ME.parse_hss('HSS3-1/2X1-1/2X3/16') == {'shape': 'rect', 'H': 3.5, 'B': 1.5, 't': 0.1875},
          ME.parse_hss('HSS3-1/2X1-1/2X3/16'))
    check('HSS parse round', ME.parse_hss('HSS5.563x0.258')['OD'] == 5.563)
    check('rebar #5', ME.rebar_size('#5')[0] == 5)
    check('rebar 16M -> #5', ME.rebar_size('16M')[0] == 5)
    check('joist parse', JO.parse_joist('18K3') == {'depth_in': 18.0, 'series': 'K', 'section': 3})
    check('grating parse', GR.parse_grating('19-W-4 1 1/2 x 3/16') == {'type': '19-W-4', 'depth_in': 1.5, 'bar_t_in': 0.1875},
          GR.parse_grating('19-W-4 1 1/2 x 3/16'))


# ------------------------------------------------------------------ builders
def test_builders():
    ax = G.unit([0.3, -0.5, 0.81])
    for fam, d in (('heavy_hex', 0.5), ('heavy_hex', 0.75), ('heavy_hex', 1.0), ('heavy_hex', 1.5), ('hex', 0.375),
                   ('hex', 0.75)):
        for wh, wn in ((0, 0), (0, 1), (1, 1)):
            it = FA.bolt_assembly([100.0, 200.0, 300.0], ax, d, 30.0, fam, x_dir=[1, 0, 0], washers_head=wh,
                                  washers_nut=wn)
            check(f'bolt {fam} {d} w{wh}{wn}: item', it is not None)
            if it:
                shape_ok(it['geometry'], f'bolt {fam} {d} w{wh}{wn}')
                again = FA.bolt_assembly([100.0, 200.0, 300.0], ax, d, 30.0, fam, x_dir=[1, 0, 0], washers_head=wh,
                                         washers_nut=wn)
                check(f'bolt {fam} {d}: deterministic', json.dumps(it, sort_keys=True) == json.dumps(again, sort_keys=True))
                check(f'bolt {fam} {d}: BLUE when the grade is data', it['colour'] == ('BLUE' if fam == 'heavy_hex' else 'AMBER'),
                      it['colour'])
    it = FA.bolt_assembly([0, 0, 0], [0, 0, 1], 0.75, 20.0, 'heavy_hex', family_source='grade inferred')
    check('bolt: inferred grade -> AMBER', it['colour'] == 'AMBER' and 'grade inferred' in it['provenance']['basis'])
    check('bolt: no row -> None', FA.bolt_assembly([0, 0, 0], [0, 0, 1], 2.5, 20.0, 'heavy_hex') is None)
    st = FA.headed_stud([0, 0, 0], [0, 0, 1], 0.75, 4.0)
    shape_ok(st['geometry'], 'stud 3/4 x 4')
    check('stud BLUE', st['colour'] == 'BLUE')
    for end in ('headed', 'hooked'):
        ar = FA.anchor_rod([0, 0, 500], [0, 0, -1], 0.75, 18.0, projection_in=4.0, end=end, plate_t_in=0.75)
        check(f'anchor {end}: item', ar is not None)
        shape_ok(ar['geometry'], f'anchor {end}')
    for nm, t_rule in (('HSS5x5x1/4', 'design'), ('HSS8X4X3/8', 'nominal'), ('HSS6.625X0.280', 'design')):
        hm = ME.hss_member(nm, [0, 0, 0], [800, 300, 1200], [0, 0, 1], t_rule=t_rule)
        shape_ok(hm['geometry'], f'{nm} skew')
        check(f'{nm}: BLUE', hm['colour'] == 'BLUE')
    hm = ME.hss_member('HSS5x5x1/4', [0, 0, 0], [0, 2000, 0], [1, 0, 0])
    a_exact = ME.hss_profile('HSS5x5x1/4')[0]
    area_in2 = G.section_area(a_exact) / IN ** 2
    check('HSS5x5x1/4 area = AISC 4.30 in2 (t_des 0.233, r 2t)', abs(area_in2 - 4.30) < 0.02, f'{area_in2:.3f}')
    rb = ME.rebar('#5', [[0, 0, 0], [1000, 0, 0]])
    shape_ok(rb['geometry'], 'rebar #5 straight')
    rb2 = ME.rebar('#5', [[0, 0, 0], [1000, 0, 0], [1000, 0, 300]])
    check('rebar bent: volume = area x path', abs(G.volume(rb2['geometry']) - math.pi * (0.625 * IN / 2) ** 2 *
                                                    sum(G.norm(G.sub(b, a)) for a, b in zip(rb2['geometry']['points'],
                                                                                            rb2['geometry']['points'][1:]))) < 1e-6)
    jo = JO.joist('18K3', [0, 0, 0], [4073.17, 0, 0], [0, 0, 1])
    shape_ok(jo['geometry'], 'joist 18K3')
    ev = jo['provenance']['evidence']
    check('joist 18K3: weight within 5 % of SJI', abs(ev['weight_plf_model'] / ev['weight_plf_target'] - 1) < 0.05,
          f"{ev['weight_plf_model']} vs {ev['weight_plf_target']}")
    check('joist always AMBER', jo['colour'] == 'AMBER')
    gp = GR.grating_panel([0, 0, 0], [1, 0, 0], [0, 0, 1], 1000.0, 600.0, 38.1)
    shape_ok(gp['geometry'], 'grating 1000 x 600')
    check('grating defaults -> AMBER', gp['colour'] == 'AMBER')
    gp2 = GR.grating_panel([0, 0, 0], [1, 0, 0], [0, 0, 1], 1000.0, 600.0, 38.1, gtype='19-W-4', bar_t_in=0.1875,
                           cross_size_in=0.25, known=('type', 'bar_t', 'cross_size'))
    check('grating from data -> BLUE', gp2['colour'] == 'BLUE')


# ------------------------------------------------------------------ the patches
def test_patches(out_dir, baselines):
    from build123d import Compound
    for tag in sorted(os.listdir(out_dir)):
        p = os.path.join(out_dir, tag, 'patch.json')
        if not os.path.exists(p):
            continue
        pa = json.load(open(p))
        base = baselines.get(tag) or {}
        n_ok = 0
        for op in pa['ops']:
            g, tg = op['geometry'], op['target']
            name = f"{tag} {op['id']}"
            try:
                sh = G.to_shape(g)
                solids = sh.solids() if hasattr(sh, 'solids') else [sh]
                ok = all(valid(s) for s in solids) and len(solids) == G.n_solids(g)
                vol = sum(s.volume for s in solids)
                vok = abs(vol - tg['volume_mm3']) <= max(tg['tol_rel'] * tg['volume_mm3'], 1e-3)
                bb = Compound(children=solids).bounding_box()
                got = [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]
                bok = max(abs(a - b) for a, b in zip(got, tg['bbox'])) <= tg['tol_mm']
                old = base.get(op.get('part_id'))
                inside = True
                if old and op['id'].split(':')[0] in ('grating', 'joist', 'hss'):
                    inside = all(got[i] >= old[i] - 1.0 for i in range(3)) and all(got[i + 3] <= old[i + 3] + 1.0 for i in range(3))
                if ok and vok and bok and inside:
                    n_ok += 1
                else:
                    check(name, False, f'valid {ok} volume {vok} ({vol:.1f} vs {tg["volume_mm3"]}) bbox {bok} '
                                       f'inside-baseline-envelope {inside}')
            except Exception as e:      # noqa: BLE001
                check(name, False, f'{type(e).__name__}: {e}')
        check(f'{tag}: all {len(pa["ops"])} ops build to target', n_ok == len(pa['ops']), f'{n_ok}/{len(pa["ops"])}')


def main(out_dir=None, baselines=None):
    for t in (test_tables, test_builders):
        try:
            t()
        except Exception:       # noqa: BLE001
            check(t.__name__, False, traceback.format_exc()[-800:])
    if out_dir:
        test_patches(out_dir, baselines or {})
    n_bad = sum(1 for r in RESULTS if not r['ok'])
    print(f'{len(RESULTS) - n_bad}/{len(RESULTS)} checks passed')
    return {'passed': len(RESULTS) - n_bad, 'total': len(RESULTS), 'failed': [r for r in RESULTS if not r['ok']]}


if __name__ == '__main__':
    r = main(os.path.join(STD, 'out'))
    sys.exit(1 if r['failed'] else 0)
