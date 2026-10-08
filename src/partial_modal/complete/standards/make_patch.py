#!/usr/bin/env python3
"""standards track: write complete/standards/out/<tag>/patch.json (schema pmp-completion-patch/1, complete/INTERFACES.md)
for the 5 new samples, from the baseline scripts tree + the source facts, with the steelstd library.

    python3 complete/standards/make_patch.py [--tags n2_db1_addon,n5_sds2]

Pure Python (no CAD kernel): GEOM + exact targets; the geometry is built and checked on Modal (modal_test.py).
Deterministic: same inputs -> byte-identical patch (generated_at is the newest input's mtime, not the clock).

What it patches (only baseline flags a standard can answer):
  n2  grating_solid_plate (34 Tekla GRTG parts)                  -> bar grating panels (AMBER: type not in the source)
      bolt_nominal_head_nut / washers (34 HILTI_HASM groups)    -> left to the db1 track (Hilti catalogue, not a standard)
  n5  bolt_from_hole_stack (143)                                -> A325 heavy hex / A307 hex + nut, RCSC length (AMBER:
                                                                   grade / head side inferred)
      joist_envelope (2 x 18K3)                                 -> SJI K joists (AMBER: chords / webs are vendor design)
      member_envelope (HSS5x5x1/4 member 8)                     -> AISC HSS along the work line (AMBER: ends)
      grating_solid_panel + plate_fallback (piece 520)          -> 19-W-4 grating, layout measured on the job's sibling
                                                                   pieces (AMBER)
      RED not_built_by_converter (3 GR1 gratings, M0001-M0003)  -> 19-W-4 gratings with the layout measured on each
                                                                   piece's own SDS/2 bar vertices (BLUE)
  n1, n3, n4: no flag a standard answers (slotted plies / open source shells / missing IFC parts) -> no patch.
Parts an earlier track (db1, sds2_ifc) already patches are skipped; a missing part a later track (estimate) also adds
is skipped too (merge order: the later op wins, two add_parts would duplicate it). Re-run after the other tracks.
"""
import argparse
import collections
import csv
import datetime
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPLETE = os.path.dirname(HERE)
ROOT = os.path.dirname(COMPLETE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(COMPLETE, 'integrate'))
from steelstd import geom as G, tables as T, fasteners as FA, members as ME, joists as JO, grating as GR  # noqa: E402
from samples import jobs, baseline_tree, SHORT  # noqa: E402

IN = T.IN
TRACK = 'standards'
EARLIER = ('db1', 'sds2_ifc')


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def rel(p):
    return os.path.relpath(p, ROOT)


def read_csv(p):
    with open(p, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


class Ctx:
    def __init__(self, tag):
        self.tag = tag
        self.job = jobs()[tag]
        self.tree = baseline_tree(tag)
        self.sched = os.path.join(self.tree, 'schedules')
        self.inputs = {}
        self.issues = self.load(os.path.join(self.sched, 'issues.json'))
        self.solids = collections.defaultdict(list)
        for r in read_csv(self.need(os.path.join(self.sched, 'solids.csv'))):
            self.solids[r['part_id']].append(r)
        self.profiles = {r['profile_id']: r for r in read_csv(self.need(os.path.join(self.sched, 'profiles.csv')))}
        self.outlines = self.load(os.path.join(self.sched, 'profile_outlines.json'))
        self.taken, self.superseded = self.earlier_patches()
        self.later_superseded = self.later_supersedes()
        self.skipped = []

    def need(self, p):
        self.inputs[rel(p)] = sha256(p)
        return p

    def load(self, p):
        return json.load(open(self.need(p), encoding='utf-8'))

    def earlier_patches(self):
        taken, sup = {}, {}
        for tr in EARLIER:
            for d in (self.tag, SHORT[self.tag]):
                p = os.path.join(COMPLETE, tr, 'out', d, 'patch.json')
                if os.path.exists(p):
                    pa = self.load(p)
                    for op in pa.get('ops') or []:
                        if op.get('part_id'):
                            taken[op['part_id']] = f"{tr}:{op.get('id')}"
                        for s in op.get('supersedes') or []:
                            sup[s] = f"{tr}:{op.get('id')}"
        return taken, sup

    def later_supersedes(self):
        """missing:<id> entries a LATER track (estimate) also supersedes with an add_part: the later op wins in the
        merge order, so ours is dropped (two add_parts for one missing part would duplicate it)"""
        sup = {}
        for d in (self.tag, SHORT[self.tag]):
            p = os.path.join(COMPLETE, 'estimate', 'out', d, 'patch.json')
            if os.path.exists(p):
                for op in self.load(p).get('ops') or []:
                    if op.get('op') == 'add_part':
                        for s in op.get('supersedes') or []:
                            sup[s] = f"estimate:{op.get('id')}"
        return sup

    def flagged(self, category):
        out = []
        for pid in sorted(self.issues['parts']):
            it = self.issues['parts'][pid]
            if any(f['category'] == category for f in it.get('flags') or []):
                out.append((pid, it))
        return out

    def free(self, pid, why):
        if pid in self.taken:
            self.skipped.append({'part_id': pid, 'why': why, 'deferred_to': self.taken[pid]})
            return False
        return True


def op_of(op_kind, op_id, item, *, part_id=None, resolves=None, supersedes=None, where=None, part=None):
    op = {'op': op_kind, 'id': op_id, 'colour': item['colour'], 'provenance': item['provenance']}
    if part_id:
        op['part_id'] = part_id
    op['geometry'] = item['geometry']
    if part is not None:
        op['part'] = part
    if resolves:
        op['resolves'] = resolves
    if supersedes:
        op['supersedes'] = supersedes
    if item.get('target'):
        op['target'] = item['target']
    if where:
        op['where'] = where
    return op


def body_frame(ctx, pid):
    """the part's single body solid row -> (origin, x, y, z, length, profile row, outline)"""
    rows = [r for r in ctx.solids[pid] if r['role'] == 'body']
    if len(rows) != 1:
        return None
    r = rows[0]
    o = [float(r['ox']), float(r['oy']), float(r['oz'])]
    x = G.unit([float(r['xx']), float(r['xy']), float(r['xz'])])
    z = G.unit([float(r['zx']), float(r['zy']), float(r['zz'])])
    vv = [float(r['vx']), float(r['vy']), float(r['vz'])]
    L = G.norm(vv)
    if G.dot(vv, z) < 0:
        z = G.mul(z, -1.0)
    y = G.cross(z, x)
    pr = ctx.profiles[r['profile_id']]
    if any(float(pr.get(k) or 0) for k in ('pos_x', 'pos_y', 'pos_angle')):
        return None
    return o, x, y, z, L, pr, ctx.outlines.get(r['profile_id'])


def rect_of(pr, outline):
    """RECT profile or an axis-aligned rectangular POLY outline -> (b, d) centred, else None"""
    if pr['kind'] == 'RECT':
        return float(pr['b']), float(pr['d'])
    if pr['kind'] == 'POLY' and outline and not outline.get('inner'):
        pts = [p for s in outline['outer'] for p in s['p']]
        xs, ys = sorted({round(p[0], 4) for p in pts}), sorted({round(p[1], 4) for p in pts})
        if len(xs) == 2 and len(ys) == 2 and abs(xs[0] + xs[1]) < 1e-3 and abs(ys[0] + ys[1]) < 1e-3:
            return xs[1] - xs[0], ys[1] - ys[0]
    return None


# ================================================================================================ n2


def patch_n2(ctx):
    ops = []
    for pid, it in ctx.flagged('grating_solid_plate'):
        if not ctx.free(pid, 'grating_solid_plate'):
            continue
        fr = body_frame(ctx, pid)
        rc = fr and rect_of(fr[5], fr[6])
        if not rc:
            ctx.skipped.append({'part_id': pid, 'why': 'grating: body is not one centred rectangular extrusion'})
            continue
        o, x, y, z, L, pr, _ = fr
        b, d = rc                                           # Tekla GRTG<b>*<d>: b = panel width, d = bar depth
        origin = G.add(o, G.add(G.mul(x, -b / 2), G.mul(y, -d / 2)))
        item = GR.grating_panel(origin, z, y, L, b, d, name=f"{pr['designation']} bar grating",
                                designation=pr['designation'],
                                extra_estimates=['bearing bars along the part axis (Tekla grating convention; the '
                                                 'record stores only width x depth)'],
                                evidence={'baseline_profile': pr['designation'], 'baseline_frame':
                                          'section x = width, section y = bar depth, extrusion = length (as the '
                                          'baseline solid)'})
        ops.append(op_of('replace_part', f'grating:{pid}', item, part_id=pid,
                         resolves=[{'part_id': pid, 'category': 'grating_solid_plate'}], where=it.get('where')))
    n_hilti = len(ctx.flagged('bolt_nominal_head_nut'))
    notes = [f'{len(ops)} Tekla GRTG parts rebuilt as NAAMM bar grating panels (AMBER: grating type, bar thickness and '
             'cross bar section are not in the DB1 record; standard 19-W-4 assumed).',
             f'{n_hilti} bolt groups flagged bolt_nominal_head_nut are standard HILTI_HASM (skipped_records.json '
             'bolt_groups[].standard): Hilti HAS-M adhesive anchor rods, a manufacturer catalogue item, not an ASTM / '
             'RCSC standard - left to the db1 track (Tekla bolt catalogue).']
    return ops, notes


# ================================================================================================ n5


def measure_grating(skipped):
    """bar layout of one SDS/2 grating piece from its own vertex records (piece-local inches)"""
    ev = skipped['source_evidence']
    pl = ev['placement']
    M, o = pl['rows_of_M'], pl['origin_mm']
    loc = set()
    for p in ev['vertices']['world_mm']:
        q = G.sub(p, o)
        loc.add(tuple(round(G.dot(M[r], q) / IN, 3) for r in range(3)))
    env = ev['vertices']['envelope']
    Lx, Wy, Dz = env['extents_in']
    y_lo = min(p[1] for p in loc)
    z_hi = max(p[2] for p in loc)
    full = [p for p in loc if p[2] < 1e-3]
    ys = sorted({round(p[1] - y_lo, 3) for p in full})
    gaps = [round(ys[i + 1] - ys[i], 3) for i in range(len(ys) - 1)]
    gc = collections.Counter(g for g in gaps if g > 0.01)
    t = min(gc, key=lambda g: (g, -gc[g]))                 # the bar thickness = the smallest repeated gap
    other = max((g for g in gc if g != t), key=lambda g: gc[g])
    pitch = round(t + other, 4)
    xs_full = sorted({p[0] for p in full})
    end_band = xs_full[1] if xs_full[1] < 0.5 else 0.0
    top = sorted({p[0] for p in loc if abs(p[2] - z_hi) > 1e-4 and p[2] > z_hi - 0.01})   # cross bar strips (z 1.499)
    strips = [(top[i], top[i + 1]) for i in range(0, len(top) - 1, 2)]
    cp = round(strips[1][0] - strips[0][0], 4) if len(strips) > 1 else None
    return {'length_in': Lx, 'width_in': Wy, 'depth_in': Dz, 'bar_t_in': t, 'bar_pitch_in': pitch,
            'end_band_in': end_band, 'cross_strip_in': strips[0] if strips else None, 'cross_pitch_in': cp,
            'n_cross': len(strips), 'n_vertices': len(ev['vertices']['world_mm']), 'M': M, 'origin_mm': o}


def gtype_of(m):
    for k, (bp, cp) in T.GRATING_TYPES.items():
        if abs(bp - m['bar_pitch_in']) < 0.01 and m['cross_pitch_in'] and abs(cp - m['cross_pitch_in']) < 0.01:
            return k
    return None


def grating_from_measure(m, origin, u, w, length_mm, width_mm, depth_mm, *, own, weight, name, extra=()):
    gt = gtype_of(m)
    cs = T.GRATING_CROSS_BAR
    c_mid = (m['cross_strip_in'][0] + m['cross_strip_in'][1]) / 2.0
    known = ('type', 'bar_t', 'bar_first', 'cross_first', 'end_band')     # measured (own piece, or siblings: below)
    est = list(extra)
    if not own:
        est.append('layout measured on the same job\'s sibling pieces of the same material (SDS/2 vertex records of '
                   f"pieces 521/523: {gt} bearing bars {T.frac(m['bar_t_in'])} in at {m['bar_pitch_in']} in from the "
                   f"edge, end bands {T.frac(m['end_band_in'])} in, cross bars every {m['cross_pitch_in']:g} in from "
                   f'{c_mid:.3f} in): this piece has no vertex record')
    it = GR.grating_panel(origin, u, w, length_mm, width_mm, depth_mm, gtype=gt, bar_t_in=m['bar_t_in'],
                          bar_first_mm=0.0, cross_first_mm=(c_mid - cs / 2.0) * IN, cross_size_in=cs,
                          end_band_t_in=m['end_band_in'], source_weight_lb=weight, known=known, name=name,
                          designation=name, extra_estimates=est,
                          evidence={'measured_in': {k: m[k] for k in ('bar_t_in', 'bar_pitch_in', 'end_band_in',
                                                                      'cross_strip_in', 'cross_pitch_in', 'n_cross',
                                                                      'n_vertices')}})
    return it


def patch_n5(ctx):
    facts = ctx.load(os.path.join(HERE, 'inputs', 'n5_sds2', 'sds2_facts.json'))
    ctx.need(os.path.join(HERE, 'inputs', 'n5_sds2', 'stage2.log'))
    inst = {i['guid']: i for i in facts['instances']}
    members = {str(m['member']): m for m in facts['members']}
    ops, notes = [], []

    # ---------------- the job's own recorded bolts: grade per diameter + the RCSC length rule check
    rec = [i['bolt'] for i in facts['instances'] if i.get('category') == 'sds2_bolt']
    grades = collections.Counter((b['dia_in'], b['type']) for b in rec)
    rule_ok = sum(1 for b in rec if FA.bolt_length(b['dia_in'], b['grip_in'])
                  and abs(FA.bolt_length(b['dia_in'], b['grip_in'])[0] - b['length_in']) < 1e-6)
    rule_txt = (f"RCSC Table C-2.2 rule (no washer allowance) reproduces the recorded length of {rule_ok}/{len(rec)} "
                f"SDS/2 bolt records of this job")
    notes.append(rule_txt + f"; recorded grades by diameter: {dict((f'{d:g} {t}', n) for (d, t), n in grades.items())}")
    for pid, it in ctx.flagged('bolt_from_hole_stack'):
        if not ctx.free(pid, 'bolt_from_hole_stack'):
            continue
        i = inst.get(pid)
        if not i or not i.get('bolt'):
            ctx.skipped.append({'part_id': pid, 'why': 'no sds2_facts instance with bolt data'})
            continue
        b = i['bolt']
        d, grip = b['dia_in'], b['grip_in']
        same = sorted({t for (dd, t) in grades if abs(dd - d) < 1e-6})
        est = ['head side as the converter placed it (its hole-stack guess; SDS/2 stores no bolt record for these)']
        if same:
            fam = FA.bolt_family(same[0])
            fsrc = (f'grade {same[0]} inferred: every SDS/2-recorded {T.frac(d)} in bolt of this job is {same[0]} '
                    f'({sum(n for (dd, t), n in grades.items() if abs(dd - d) < 1e-6)} records)')
            wtxt = 'no washers, as the job\'s recorded bolts (' + rule_txt + ')'
        else:
            fam = 'hex'
            fsrc = (f'grade A307 (hex bolt + hex nut) inferred: no {T.frac(d)} in bolt is recorded in this job and '
                    f'ASTM F3125 structural grades start at 1/2 in, so A307 is the ASTM bolt of this diameter')
            wtxt = 'no washers (A307 in standard holes; none recorded for this job\'s bolts)'
        est.append(wtxt)
        item = FA.bolt_assembly(i['origin_mm'], i['z'], d, grip * IN, fam, x_dir=i['x'], family_source=fsrc,
                                estimates=est, evidence={'sds2_instance': i['label'], 'hole_stack_grip_in': grip},
                                name=f"BOLT {T.frac(d)} x grip {grip:g}")
        if item is None:
            ctx.skipped.append({'part_id': pid, 'why': f'no table row for {d} in'})
            continue
        ops.append(op_of('replace_part', f'bolt:{pid}', item, part_id=pid,
                         resolves=[{'part_id': pid, 'category': 'bolt_from_hole_stack'}], where=it.get('where')))

    # ---------------- joists
    for pid, it in ctx.flagged('joist_envelope'):
        if not ctx.free(pid, 'joist_envelope'):
            continue
        i = inst[pid]
        m = members[str(i['member'])]
        item = JO.joist(m['section']['name'], m['p1_mm'], m['p2_mm'], [0.0, 0.0, 1.0],
                        evidence={'sds2_member': i['member'], 'work_line_mm': [m['p1_mm'], m['p2_mm']],
                                  'sds2_section': m['section']}, name=i['label'].replace(' (member envelope)', ''))
        ops.append(op_of('replace_part', f'joist:{pid}', item, part_id=pid,
                         resolves=[{'part_id': pid, 'category': 'joist_envelope'}], where=it.get('where')))

    # ---------------- member envelope (HSS without fabricated pieces)
    for pid, it in ctx.flagged('member_envelope'):
        if not ctx.free(pid, 'member_envelope'):
            continue
        i = inst[pid]
        m = members[str(i['member'])]
        sec = m['section']['name']
        p = ME.parse_hss(sec)
        if not p or p['shape'] != 'rect':
            ctx.skipped.append({'part_id': pid, 'why': f'member envelope section {sec} is not a rectangular HSS'})
            continue
        drop = p['H'] * IN / 2.0                                       # top of steel on the work line (as the envelope)
        s = G.add(m['p1_mm'], [0.0, 0.0, -drop])
        e = G.add(m['p2_mm'], [0.0, 0.0, -drop])
        xd = G.cross([0.0, 0.0, 1.0], G.unit(G.sub(e, s)))
        item = ME.hss_member(sec, s, e, xd, estimates=[
            'member length = the work-line length and square ends: the SDS/2 job has no fabricated piece for '
            'this member (setbacks / end connections unknown)',
            'top of steel on the work line (as the baseline envelope)'],
            evidence={'sds2_member': i['member'], 'work_line_mm': [m['p1_mm'], m['p2_mm']], 'sds2_section':
                      m['section']}, part_name=i['label'].replace(' (member envelope)', ''))
        ops.append(op_of('replace_part', f'hss:{pid}', item, part_id=pid,
                         resolves=[{'part_id': pid, 'category': 'member_envelope'}], where=it.get('where')))

    # ---------------- gratings: the 3 skipped pieces (own vertex records) and piece 520 (siblings)
    miss = ctx.load(os.path.join(ctx.sched, 'missing_parts.json'))['parts']
    meas = {}
    for s in facts['skipped']:
        if not str(s['name']).upper().startswith('GR') or not s['source_evidence'].get('vertices'):
            continue
        key = (str(s['member']), str(s['piece']), str(s['inst']))
        meas[key] = (s, measure_grating(s))
    for mp in miss:
        evd = mp.get('evidence') or {}
        key = (str(evd.get('member')), str(evd.get('piece')), str(evd.get('inst')))
        if key not in meas:
            continue
        sid = f"missing:{mp['id']}"
        if sid in ctx.superseded or sid in ctx.later_superseded:
            ctx.skipped.append({'missing': mp['id'], 'why': 'grating (another track adds this missing part)',
                                'deferred_to': ctx.superseded.get(sid) or ctx.later_superseded[sid]})
            continue
        s, m = meas[key]
        Mx, My, Mz = [G.v(r) for r in m['M']]
        W = m['width_in'] * IN
        origin = G.add(m['origin_mm'], G.mul(My, -W))
        wt = s['source_evidence']['piece_table']['weight_lb']
        nm = f"{s['name']} (SDS/2 MISC #{s['member']}, piece {s['piece']}, inst {s['inst']})"
        item = grating_from_measure(m, origin, Mx, Mz, m['length_in'] * IN, W, m['depth_in'] * IN, own=True,
                                    weight=wt, name=nm)
        part = dict(item['part'], part_mark=f"P{s['piece']}", assembly_mark=f"M{s['member']}")
        ops.append(op_of('add_part', f"grating:{mp['id']}", item, part=part, supersedes=[sid],
                         where=mp.get('where')))
    sib = next((m for (s, m) in meas.values() if s['name'] == 'GR1 1/2x35 13/16'), None)
    for pid, it in ctx.flagged('grating_solid_panel'):
        if not ctx.free(pid, 'grating_solid_panel') or sib is None:
            continue
        fr = body_frame(ctx, pid)
        rc = fr and rect_of(fr[5], fr[6])
        if not rc:
            ctx.skipped.append({'part_id': pid, 'why': 'grating panel body is not a centred rectangle'})
            continue
        o, x, y, z, L, pr, _ = fr
        b, d = rc
        origin = G.add(o, G.add(G.mul(x, -b / 2), G.mul(y, -d / 2)))
        solid_lb = b * d * L * GR.LB_PER_MM3
        wt = round(solid_lb - 721.0, 1)                     # converter log: 'largest differences (lb...): (721, 520 ...)'
        item = grating_from_measure(sib, origin, z, y, L, b, d, own=False, weight=wt, name=inst[pid]['label'],
                                    extra=['bearing bars along the panel length (as on every sibling piece)'])
        item['provenance']['evidence']['weight_lb_source_note'] = (
            f'SDS/2 piece weight = the fallback solid {solid_lb:.1f} lb - 721 lb (converter log stage2.log line '
            '"largest differences"), +-0.5 lb')
        ops.append(op_of('replace_part', f'grating:{pid}', item, part_id=pid,
                         resolves=[{'part_id': pid, 'category': 'grating_solid_panel'},
                                   {'part_id': pid, 'category': 'plate_fallback'}], where=it.get('where')))
    notes.append('concrete_prism (1) is not a standard item: left to the other tracks.')
    return ops, notes


MAKERS = {'n2_db1_addon': patch_n2, 'n5_sds2': patch_n5}
NO_PATCH = {'n1_db1_small': 'flags are slotted plies / fittings / duplicates (DB1 decoding, not a standard)',
            'n3_ifc_approx': 'baseline failed before schedules; its gap (6 IFC parts not in the STEP) is not a standard item',
            'n4_ifc_c2s': 'flags are open source shells (surface models), not a standard item'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tags', default=','.join(MAKERS))
    a = ap.parse_args()
    lib = sorted(os.path.join(HERE, 'steelstd', f) for f in os.listdir(os.path.join(HERE, 'steelstd'))
                 if f.endswith('.py'))
    for tag in a.tags.split(','):
        if tag not in MAKERS:
            print(f'{tag}: no standards patch ({NO_PATCH.get(tag, "unknown tag")})')
            continue
        ctx = Ctx(tag)
        for p in lib + [os.path.abspath(__file__)]:
            ctx.need(p)
        ops, notes = MAKERS[tag](ctx)
        newest = max(os.path.getmtime(os.path.join(ROOT, p)) for p in ctx.inputs)
        patch = {'schema': 'pmp-completion-patch/1', 'track': TRACK, 'tag': tag, 'model_id': ctx.job['model_id'],
                 'generated_by': 'complete/standards/make_patch.py',
                 'generated_at': datetime.datetime.fromtimestamp(newest, datetime.timezone.utc).strftime(
                     '%Y-%m-%dT%H:%M:%SZ'),
                 'inputs': dict(sorted(ctx.inputs.items())), 'ops': ops,
                 'notes': notes + ([f'skipped: {json.dumps(ctx.skipped)}'] if ctx.skipped else [])}
        out = os.path.join(HERE, 'out', tag)
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, 'patch.json'), 'w', encoding='utf-8') as f:
            json.dump(patch, f, indent=1, sort_keys=False)
            f.write('\n')
        cnt = collections.Counter((o['op'], o['colour']) for o in ops)
        print(f'{tag}: {len(ops)} ops {dict(cnt)}; skipped {len(ctx.skipped)}')


if __name__ == '__main__':
    main()
