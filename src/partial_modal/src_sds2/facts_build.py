#!/usr/bin/env python3
"""sds2_facts.json: what the SDS/2 converter did to every instance of the shipped STEP, for the issue maker
(standard library only). Built from the converter run that reproduced the shipped STEP byte for byte:

  <base>_pieces.csv / _skipped.csv / _manifest.json (v5.x)   the converter's own side tables, as it wrote them
  <base>_ifc_products.jsonl                                    the IFC emitter's rows (label, GlobalId, IFC class)
  <base>_facts_instances.jsonl                                 facts_hooks: placement, bbox, hole tools per instance
  <base>_facts_convert.json                                    facts_hooks: stats, holes per piece, skipped pieces with
                                                               their SDS/2 source geometry, members + work lines

Per instance (key = guid, the pipeline's part id): label, member / member type / piece / inst / piece name (from the
label), the pieces.csv row (kind, builder, v5 standin text), a factual category, IFC class, placement, bbox, holes.
category (derived only from what the converter recorded; never a colour - the issue maker decides colours):
  exact                  builder exact_brep, no stand-in note, no '[approx' in the label
  sds2_bolt              'BOLT ...' instance from an SDS/2 bolt record (label without 'nominal')
  nominal_bolt           'BOLT ... (nominal heavy hex)': a bolt guessed from a coaxial hole stack (no bolt record)
  member_envelope        member without fabricated pieces written as its work-line section envelope (builder
                         member_envelope; also a main material stored flat, written as its member's envelope)
  joist_envelope         v4: joist without pieces written as its work-line envelope box (builder joist_envelope_approx)
  joist_standin          v5: open-web joist stand-in sized from its designation (builder joist_openweb_standin)
  concrete_prism         concrete written as its L x W x T prism (special_primitive, kind concrete)
  turned_primitive       studs / rods / anchors (special_primitive, not concrete): cylinders from the piece's mesh
                         rings, or from its piece-table diameter x length when it has none (v5 standin text says which)
  approximated           any other non-exact builder (plate / profile / bent-plate fallback, piece_table_standin ...)
  flagged_exact          exact_brep but the converter attached a stand-in / approx note (v5 standin column or label)
  unknown                instance with no pieces.csv row and no recognised label (reported, never guessed)
usage: facts_build.py BASE OUT.json --model-id ID --shipped-sha256 SHA [--pin PIN.json] [--partial PARTIAL.json]"""
import collections, csv, json, os, re, sys

LABEL_RX = re.compile(r"^\s*(.*?)\s*#(\d+) / (.*?) \(piece (\d+), inst (\d+)\)")
ENV_RX = re.compile(r"^\s*(.*?)\s*#(\d+) / (.*?) \((member envelope|joist stand-in)\)")
BOLT_RX = re.compile(r"^BOLT (?:(?P<ty>.*?) )?(?P<d>[0-9.]+) x (?P<L>[0-9.]+)(?: \(grip (?P<g>[0-9.]+)\)| grip)")
APPROX_BUILDERS = {'plate_fallback', 'profile_fallback', 'bent_plate_fallback', 'piece_table_standin', 'plate_from_vertices'}
GRATING_RX = re.compile(r'^(GT|GR)\d')


def _csv(path):
    if not os.path.exists(path):
        return None
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def _json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _jsonl(path):
    out = []
    if os.path.exists(path):
        with open(path) as f:
            for ln in f:
                if ln.strip():
                    out.append(json.loads(ln))
    return out


def _int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def category(row, label, bolt):
    if bolt is not None:
        return 'nominal_bolt' if bolt['source'] == 'nominal' else 'sds2_bolt'
    if row is None:
        return 'unknown'
    b = row.get('builder') or ''
    k = row.get('kind') or ''
    flagged = bool((row.get('standin') or '').strip()) or '[approx' in label
    if b == 'exact_brep':
        return 'flagged_exact' if flagged else 'exact'
    if b == 'member_envelope':
        return 'member_envelope'
    if b == 'joist_envelope_approx':
        return 'joist_envelope'
    if b == 'joist_openweb_standin':
        return 'joist_standin'
    if b == 'special_primitive':
        return 'concrete_prism' if k == 'concrete' else 'turned_primitive'
    return 'approximated'


IN = 25.4
TOL_DIM_IN = 1.0 / 16.0           # a recorded dimension confirms the vertex envelope within 1/16 in
STEEL_LB_PER_IN3 = 0.2836
ENVELOPE_MARGIN_MM = 2000.0        # a skipped piece's vertices must lie within the model's parts box + this margin
DIM = r'(\d+(?:\.\d+)?(?:[ -]+\d+/\d+)?|\d+/\d+)'
NAME_DIMS_RX = re.compile(r'^\s*([A-Za-z]+)\s*' + DIM + r'\s*[xX]\s*' + DIM)


def _inch(s):
    """'1 1/2' -> 1.5, '35 13/16' -> 35.8125, '3/8' -> 0.375, '6' -> 6.0"""
    tot = 0.0
    for tok in re.split(r'[ -]+', s.strip()):
        if '/' in tok:
            n, d = tok.split('/')
            tot += float(n) / float(d)
        elif tok:
            tot += float(tok)
    return tot


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _bbox_union(inst):
    lo, hi = [float('inf')] * 3, [float('-inf')] * 3
    for r in inst:
        b = r.get('bbox_mm')
        if b:
            for i in range(3):
                lo[i], hi[i] = min(lo[i], b[0][i]), max(hi[i], b[1][i])
    return (lo, hi) if lo[0] != float('inf') else None


def skipped_geometry(row, parts_box):
    """RED geometry for one skipped piece, ONLY from what the SDS/2 job records and only when a second source record
    confirms it (else 'geometry_withheld' says why and the issue maker falls back to a labelled marker).

    Candidate: the convex hull of the piece's own vertex records on its two largest local axes, extruded over their
    range along the thinnest one (facts_hooks._envelope), placed by the member-file placement (world = o + M.T @ local).
    Gating sanity: placement found, M orthonormal, non-degenerate extents, hull >= 3 points, vertices inside the model's
    parts box + 2 m (a fallback_over_5x_source_weight skip can come from coinciding / corrupt vertices).
    Confirmation (any one): the piece name's 'D x W' designation (SDS/2 'GR1 1/2x35 13/16', 'PL3/8x6': depth /
    thickness x width) equals the envelope's thickness and one in-plane extent within 1/16 in; or the piece table's
    L / W / T equal the envelope's three extents within 1/16 in; or the envelope's steel weight is 0.67 - 1.5 x the
    piece table weight. The member work line length vs the long extent is recorded as a further check only."""
    ev = row.get('source_evidence') or {}
    pl, vx, pt = ev.get('placement'), ev.get('vertices') or {}, ev.get('piece_table') or {}
    env = vx.get('envelope')
    checks = {}
    if not pl:
        return None, 'no placement of this piece found in its member file', checks
    if not env or not env.get('hull_in'):
        return None, 'no vertex envelope recorded for this piece' + (f" ({vx['envelope_error']})" if vx.get('envelope_error') else ''), checks
    M, o = pl['rows_of_M'], pl['origin_mm']
    ortho = max(abs(_dot(M[i], M[j]) - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3))
    checks['placement_orthonormal_dev'] = round(ortho, 9)
    if ortho > 1e-6:
        return None, f'placement matrix is not orthonormal (dev {ortho:.2e})', checks
    t, (a, b) = env['thickness_axis'], env['plane_axes']
    ext = env['extents_in']
    T = ext[t]
    if T <= 1e-3 or ext[a] <= 1e-2 or ext[b] <= 1e-2 or len(env['hull_in']) < 3:
        return None, f'degenerate vertex envelope (extents {ext} in, {len(env["hull_in"])} hull points)', checks
    n = _cross(M[a], M[b])
    s = 1.0 if _dot(n, M[t]) > 0 else -1.0
    t0 = env['range_t_in'][0] if s > 0 else env['range_t_in'][1]
    outline = [[round(o[i] + IN * (u * M[a][i] + v * M[b][i] + t0 * M[t][i]), 4) for i in range(3)] for u, v in env['hull_in']]
    top = [[round(p[i] + n[i] * T * IN, 4) for i in range(3)] for p in outline]
    lo = [min(p[i] for p in outline + top) for i in range(3)]
    hi = [max(p[i] for p in outline + top) for i in range(3)]
    if parts_box is None:
        return None, 'no delivered part box to check the vertices against', checks
    plo, phi = parts_box
    inside = all(plo[i] - ENVELOPE_MARGIN_MM <= lo[i] and hi[i] <= phi[i] + ENVELOPE_MARGIN_MM for i in range(3))
    checks['inside_model_parts_box_plus_2m'] = inside
    if not inside:
        return None, 'the recorded vertices reach outside the model\'s parts box + 2 m (corrupt vertices?)', checks
    env_wt = env['hull_area_in2'] * T * STEEL_LB_PER_IN3
    wt = pt.get('weight_lb') or 0.0
    checks['envelope_steel_weight_lb'] = round(env_wt, 1)
    checks['piece_table_weight_lb'] = wt
    checks['weight_ratio'] = round(env_wt / wt, 3) if wt and wt > 0 else None
    confirmed = []
    m = NAME_DIMS_RX.match(row.get('name') or pt.get('name') or '')
    if m:
        D, Wd = _inch(m.group(2)), _inch(m.group(3))
        ok = abs(T - D) <= TOL_DIM_IN and min(abs(ext[a] - Wd), abs(ext[b] - Wd)) <= TOL_DIM_IN
        checks['name_dims'] = dict(prefix=m.group(1), depth_or_thickness_in=D, width_in=Wd, envelope_thickness_in=T,
                                   envelope_plane_in=[ext[a], ext[b]], match=ok)
        if ok:
            confirmed.append(f"its name '{row.get('name')}' ({D:g} in x {Wd:g} in)")
    L_, W_, T_ = (pt.get('L_in') or 0.0), (pt.get('W_in') or 0.0), (pt.get('T_in') or 0.0)
    if min(L_, W_, T_) > 0:
        ok = all(abs(x - y) <= TOL_DIM_IN for x, y in zip(sorted(ext), sorted([L_, W_, T_])))
        checks['piece_table_LWT'] = dict(L_in=L_, W_in=W_, T_in=T_, match=ok)
        if ok:
            confirmed.append(f'the piece table size {L_:g} x {W_:g} x {T_:g} in')
    if checks['weight_ratio'] is not None and 0.67 <= checks['weight_ratio'] <= 1.5:
        confirmed.append(f"the piece table weight ({wt:g} lb vs {env_wt:.0f} lb for the envelope)")
    mem = ev.get('member') or {}
    if mem.get('p1_mm') and mem.get('p2_mm'):
        wl = sum((mem['p2_mm'][i] - mem['p1_mm'][i]) ** 2 for i in range(3)) ** 0.5 / IN
        checks['member_work_line_in'] = round(wl, 4)
        checks['long_extent_equals_work_line'] = abs(max(ext[a], ext[b]) - wl) <= 2 * TOL_DIM_IN
    checks['confirmed_by'] = confirmed
    if not confirmed:
        return None, ('the vertex envelope (%s in) is not confirmed by the name, the piece table size or weight '
                      '(envelope %.0f lb vs %s lb)' % (' x '.join('%g' % e for e in ext), env_wt, wt)), checks
    grating = bool(GRATING_RX.match(row.get('name') or ''))
    what = ((f"solid envelope of the bar grating panel {row.get('name')} ({max(ext[a], ext[b]):g} x {min(ext[a], ext[b]):g} "
             f"in, {T:g} in deep); the bars are not modelled - SDS/2 weighs the open mesh ({wt:g} lb vs {env_wt:.0f} lb "
             f"for the solid envelope)") if grating else
            f"outline of the piece's {vx.get('n')} recorded vertices, {T * IN:.1f} mm thick ({T:g} in)")
    geom = dict(kind='prism_world', outline_world=outline, normal=[round(v, 9) for v in n], thickness=round(T * IN, 4),
                offset=0.0, what=what,
                basis='convex hull of the piece\'s own vertex records x their range along its thinnest local axis, placed '
                      'by the member file placement; confirmed by ' + '; '.join(confirmed))
    return geom, None, checks


def build(base, model_id, shipped_sha, pin=None, partial=None):
    pieces = _csv(base + '_pieces.csv')
    skipped_csv = _csv(base + '_skipped.csv')
    manifest = _json(base + '_manifest.json')
    prod = {r['guid']: r for r in _jsonl(base + '_ifc_products.jsonl')}
    fin = _jsonl(base + '_facts_instances.jsonl')
    fmeta = _json(base + '_facts_instances_meta.json') or {}
    fconv = _json(base + '_facts_convert.json') or {}
    emit = _json(base + '_ifc_emit.json') or {}
    errors = []
    if os.path.exists(base + '_facts_error.txt'):
        errors.append(open(base + '_facts_error.txt').read()[-4000:])
    if pieces is None:
        errors.append('converter wrote no _pieces.csv')
    by_piece, by_env, used = {}, {}, set()
    for i, r in enumerate(pieces or []):
        m, p, n = _int(r.get('member')), _int(r.get('piece')), _int(r.get('inst'))
        if p:
            by_piece.setdefault((m, p, n), []).append(i)
        else:
            by_env.setdefault(m, []).append(i)
    inst = []
    cats, builders, classes = collections.Counter(), collections.Counter(), collections.Counter()
    bolts = collections.Counter()
    standin_groups = collections.OrderedDict()
    for f in fin:
        label = f['label']
        pr = prod.get(f['guid']) or {}
        r = dict(guid=f['guid'], label=label, part=f.get('part'), ifc_class=pr.get('cls'), ifc_emitted=pr.get('emitted'),
                 origin_mm=f.get('origin_mm'), x=f.get('x'), z=f.get('z'), bbox_mm=f.get('bbox_mm'))
        if f.get('holes'):
            r['holes'] = f['holes']
        row, bolt = None, None
        ls = label.strip()
        if ls.startswith('BOLT'):
            m = BOLT_RX.match(ls)
            bolt = dict(source='nominal' if 'nominal' in ls else 'sds2')
            if m:
                bolt.update(dia_in=float(m.group('d')), type=(m.group('ty') or None))
                if bolt['source'] == 'nominal':
                    bolt.update(grip_in=float(m.group('L')), length_in=None)
                else:
                    bolt.update(length_in=float(m.group('L')), grip_in=float(m.group('g')) if m.group('g') else None)
            r['bolt'] = bolt
            bolts[bolt['source']] += 1
        else:
            m = LABEL_RX.match(label)
            e = ENV_RX.match(label) if not m else None
            if m:
                r.update(member_type=m.group(1), member=int(m.group(2)), name=m.group(3), piece=int(m.group(4)),
                         inst=int(m.group(5)))
                cand = [i for i in by_piece.get((r['member'], r['piece'], r['inst']), []) if i not in used]
            elif e:
                r.update(member_type=e.group(1), member=int(e.group(2)), name=e.group(3), piece=0, inst=0)
                cand = [i for i in by_env.get(r['member'], []) if i not in used]
            else:
                cand = []
            if cand:
                used.add(cand[0])
                row = pieces[cand[0]]
                r.update(kind=row.get('kind'), builder=row.get('builder'))
                if (row.get('standin') or '').strip():
                    r['standin'] = row['standin']
                if (row.get('also_on_member') or '').strip():
                    r['also_on_member'] = row['also_on_member']
        if '[approx' in label:
            r['label_approx_note'] = label[label.index('[approx'):]
        if r.get('name') and GRATING_RX.match(r['name']):
            r['grating_name'] = True
        c = category(row, label, bolt)
        r['category'] = c
        cats[c] += 1
        builders[r.get('builder') or ('bolt_' + bolt['source'] if bolt else 'none')] += 1
        classes[r.get('ifc_class')] += 1
        if c not in ('exact',):
            key = (c, r.get('builder'), (r.get('name') if c not in ('sds2_bolt', 'nominal_bolt', 'unknown') else None))
            g = standin_groups.setdefault(key, dict(category=c, builder=r.get('builder'), name=key[2], count=0, guids=[]))
            g['count'] += 1
            g['guids'].append(r['guid'])
        inst.append(r)
    unmatched_rows = [pieces[i] for i in range(len(pieces or [])) if i not in used]
    sk = fconv.get('skipped')
    if sk is None and skipped_csv is not None:
        sk = [dict(r, source_evidence=None) for r in skipped_csv]
    parts_box = _bbox_union(inst)
    n_geom = 0
    for r in (sk or []):
        try:
            g, why, checks = skipped_geometry(r, parts_box)
        except Exception as e:
            g, why, checks = None, f'geometry check failed: {type(e).__name__}: {e}', {}
        r['geometry_checks'] = checks
        if g:
            pts = g['outline_world'] + [[p[i] + g['normal'][i] * g['thickness'] for i in range(3)] for p in g['outline_world']]
            r['geometry'] = g
            r['bbox'] = [round(min(p[i] for p in pts), 4) for i in range(3)] + [round(max(p[i] for p in pts), 4) for i in range(3)]
            n_geom += 1
        else:
            r['geometry'] = None
            r['geometry_withheld'] = why
    mems = fconv.get('members') or []
    with_rows = {_int(r.get('member')) for r in (pieces or [])} | {_int(r.get('member')) for r in (skipped_csv or [])}
    mwg = [m for m in mems if m['member'] not in with_rows and m.get('type') != 'Ref Point']
    holes_tools = sum(len(r.get('holes', [])) for r in inst)
    out = dict(
        schema='pmp-sds2-facts/1', model_id=model_id, shipped_step_sha256=shipped_sha,
        converter=pin, sds2_job_version=fconv.get('job_version'), root=fmeta.get('root') or emit.get('root'),
        units='mm, world coordinates of the shipped STEP (origin_mm, bbox_mm, holes, work lines); *_in = SDS/2 inches',
        counts=dict(instances=len(inst), unique_parts=fmeta.get('unique_parts'), by_category=dict(cats),
                    by_builder=dict(builders), by_ifc_class={str(k): v for k, v in classes.items()},
                    bolts_sds2=bolts.get('sds2', 0), bolts_nominal=bolts.get('nominal', 0),
                    pieces_rows=len(pieces or []), pieces_rows_without_instance=len(unmatched_rows),
                    skipped=len(sk or []), skipped_by_reason=dict(collections.Counter(r.get('reason') for r in (sk or []))),
                    skipped_with_geometry=n_geom,
                    members=len(mems), members_without_geometry=len(mwg),
                    instances_with_cut_holes=sum(1 for r in inst if r.get('holes')), hole_tools_placed=holes_tools,
                    pieces_with_decoded_holes=len(fconv.get('holes_by_piece') or {}),
                    decoded_holes=sum(v['n'] for v in (fconv.get('holes_by_piece') or {}).values())),
        converter_stats=fconv.get('stats'), converter_holes_cut_counter=fconv.get('holes_cut_counter'),
        converter_manifest=manifest,
        standin_groups=list(standin_groups.values()),
        skipped=sk or [],
        members_without_geometry=mwg,
        members=mems,
        pieces_rows_without_instance=unmatched_rows[:200],
        holes_by_piece=fconv.get('holes_by_piece'),
        partial_record=partial,
        notes=[
            'categories come only from what the converter recorded (builder / kind / standin columns, instance labels); '
            'a v4 converter writes no standin column and no manifest: its stand-ins are known by builder and label only',
            'skipped[]: pieces the converter did not write (its _skipped.csv), each with the geometry the SDS/2 job records '
            'for it (source_evidence: piece-table size and weight, placement from the member file, the piece\'s own '
            'vertices); a piece whose source vertices were rejected (e.g. fallback_over_5x_source_weight) may hold corrupt '
            'vertices - the piece-table size is the other source record',
            'skipped[].geometry (kind prism_world: outline_world mm, normal, thickness mm, offset 0, plus what / basis) is '
            'given ONLY when the hull of the piece\'s own vertex records is inside the model\'s parts box + 2 m AND is '
            'confirmed by a second source record (its name\'s D x W designation, its piece-table L x W x T, or its '
            'piece-table weight); geometry_checks holds every check, geometry_withheld says why there is none (the issue '
            'maker then draws a labelled marker at the recorded origin). bbox = [xmin, ymin, zmin, xmax, ymax, zmax] mm',
            'members_without_geometry[]: members (not Ref Point) with no row in _pieces.csv or _skipped.csv: the converter '
            'wrote nothing for them; work line + section are what the SDS/2 job records. members[]: every member of the '
            'job (id, type, work line p1_mm -> p2_mm, roll, section) - landmarks for locating parts',
            'holes: per instance, the tools the converter actually cut (world mm: kind, start point, axis, radius, length '
            '[, slot half length]); holes_by_piece: holes decoded from the piece files (piece-local)'],
        errors=errors + (fconv.get('errors') or []),
        instances=inst)
    return out


if __name__ == '__main__':
    a = sys.argv[1:]

    def opt(k):
        return a[a.index(k) + 1] if k in a else None
    base, outp = a[0], a[1]
    pin = _json(opt('--pin')) if opt('--pin') else None
    partial = _json(opt('--partial')) if opt('--partial') else None
    res = build(base, opt('--model-id'), opt('--shipped-sha256'), pin, partial)
    with open(outp, 'w') as f:
        json.dump(res, f, separators=(',', ':'))
    print(json.dumps(res['counts']))
