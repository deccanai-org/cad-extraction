#!/usr/bin/env python3
"""db1_facts.py CONFIG.json  ->  skipped_records.json        (container side; runs in the decoder venv /opt/conv/ifc84)

What the DB1 records hold for everything the conversion did NOT write (or wrote approximately), with the geometry the
SOURCE records, so that the issue maker can draw RED parts from source-recorded geometry only (never invented):
  skipped           every decoded record the converter skipped (reason = the converter's own): record id, profile string,
                    attribute strings, axis O / E / L / local frame x, y, z, contour outline (local + world) when the DB1
                    holds one, the number in the profile name (the converter's own contour-plate thickness rule)
  dropped_by_step_writer   parts the decoder wrote into the IFC but the STEP stage dropped (in model.ifc, not in the STEP)
  cut_bodies        every cut body (built / unbuilt, parents, applied or not)
  fittings_not_applied     members whose Tekla fittings / line cuts were decoded but not applied (+ the fitting planes)
  bolt_groups       every decoded bolt group: written as / gid, bolts (world centres, axis, d, L), plies, slot decision
                    (slotted groups whose plies were cut ROUND), nominal head / nut, axial position, washer flags
  parts             the converter's own parts list [seq, profile, category, status, how, GlobalId, in_shipped_step, n_cuts]
                    with the GlobalIds of the FINAL IFC (= the shipped STEP PRODUCT ids for every product in the STEP)

How: the pinned kit (byte-identical to the one that produced the shipped STEP, md5-checked by regen_core.py) is imported
read-only and its own converter is run once more exactly as convert_one.py runs it (same catalog + overlay merge, layout,
variants, full-discovery flag). sys.settrace captures the local variables of db1step._convert / convert_old at return
(line events off: no behaviour change, no edited kit file). The decode is then PROVEN to be the reproducing one: its parts
list must equal (every field except the random GlobalId) the parts list of the regeneration that reproduced the shipped
STEP, and the conversion fleet's own decoded_parts (when given). usable_for_red_parts is true only when every available
comparison is equal. Deterministic: no wall times, no paths, floats rounded to 1e-3 mm, sorted keys.

CONFIG.json {kit_dir, kit, code, model_id, db1, layout, variants, full_discovery, out,
             repro_parts|null (convert.json.parts.json.gz of the reproducing run), gid_map|null (regenerated GlobalId ->
             final IFC GlobalId, every IfcRoot), shipped_step (path), fleet_decoded_parts|null}
Prints one JSON line (summary)."""
import collections, gzip, hashlib, json, math, os, re, shutil, sys, tempfile, traceback

SCHEMA = 'pmp.src_db1.skipped_records/1'
ASCII = re.compile(rb'[\x20-\x7e]{3,}')
PROD = re.compile(rb"^#\d+=PRODUCT\('([^']*)'")


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def clean(o, nd=3):
    """JSON-safe, deterministic: numpy -> python, floats rounded, tuples -> lists, sets -> sorted lists"""
    try:
        import numpy as np
        if isinstance(o, np.ndarray):
            o = o.tolist()
        elif isinstance(o, np.generic):
            o = o.item()
    except Exception:
        pass
    if isinstance(o, bool) or o is None or isinstance(o, str):
        return o
    if isinstance(o, int):
        return o
    if isinstance(o, float):
        if not math.isfinite(o):
            return None
        v = round(o, nd)
        return 0.0 if v == 0 else v
    if isinstance(o, dict):
        return {str(k): clean(v, nd) for k, v in o.items()}
    if isinstance(o, (set, frozenset)):
        return sorted(clean(v, nd) for v in o)
    if isinstance(o, (list, tuple)):
        return [clean(v, nd) for v in o]
    if isinstance(o, bytes):
        return o.decode('latin-1')
    return str(o)


def vec(v):
    try:
        return [float(x) for x in v][:3]
    except Exception:
        return None


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def unit(a):
    n = math.sqrt(sum(x * x for x in a))
    return [x / n for x in a] if n > 1e-12 else None


def bbox(points):
    pts = [p for p in points if p]
    if not pts:
        return None
    return [min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]


def profile_number(prof):
    """the converter's contour-plate thickness rule: float(re.findall(r'[\\d.]+', prof)[0])"""
    if not prof:
        return None
    m = re.findall(r'[\d.]+', prof)
    if not m:
        return None
    try:
        return float(m[0])
    except ValueError:
        return None


def capture(kit_dir, db1, layp, varp, full, workdir):
    """run the kit's converter exactly as convert_one.py does; capture _convert / convert_old locals at return"""
    sys.path.insert(0, kit_dir)
    os.environ['DB1_SHA256'] = sha256(db1)
    import db1step
    lay = json.load(open(layp)) if os.path.exists(layp) else None
    variants = json.load(open(varp)) if varp and os.path.exists(varp) else []
    cat = json.load(open(os.path.join(kit_dir, 'tekla_profiles.json')))
    ovp = os.path.join(kit_dir, 'tekla_profiles_overlay.json')            # convert_one.py's db1prof-patch, same code
    if os.path.exists(ovp):
        ov = json.load(open(ovp))
        h = os.environ['DB1_SHA256']
        for src in (ov.get('global') or {}, (ov.get('per_model') or {}).get(h) or {}):
            cat.update({k: {'kind': v['kind'], 'dims': v['dims'], 'overlay': v.get('src')} for k, v in src.items()})
    targets = {db1step._convert.__code__: 'new', db1step.convert_old.__code__: 'old'}
    CAP = {}

    def local_tracer(frame, event, arg):
        if event == 'return':
            CAP[targets[frame.f_code]] = dict(frame.f_locals)
        return local_tracer

    def global_tracer(frame, event, arg):
        if event == 'call' and frame.f_code in targets:
            frame.f_trace_lines = False
            return local_tracer
        return None

    tmp_ifc = os.path.join(workdir, 'facts_rerun.ifc')
    sys.settrace(global_tracer)
    try:
        st = db1step.convert(db1, tmp_ifc, cat, lay or None, variants, allow_full=full)
    finally:
        sys.settrace(None)
    try:
        os.remove(tmp_ifc)
    except OSError:
        pass
    return st, CAP, cat, db1step


def strip_gid(p):
    return [p[0], p[1], p[2], p[3], p[4], p[6] if len(p) > 6 else None]


def compare_plists(a, b):
    sa = [strip_gid(p) for p in a]
    sb = [strip_gid(p) for p in b]
    diffs = []
    for i in range(max(len(sa), len(sb))):
        x = sa[i] if i < len(sa) else None
        y = sb[i] if i < len(sb) else None
        if x != y:
            diffs.append({'index': i, 'this_decode': x, 'reference': y})
            if len(diffs) >= 5:
                break
    return {'equal': sa == sb, 'entries_this_decode': len(sa), 'entries_reference': len(sb), 'first_differences': diffs}


def shipped_product_ids(path):
    ids = set()
    with open(path, 'rb') as f:
        for line in f:
            if line.startswith(b'#') and b'=PRODUCT(' in line[:40]:
                m = PROD.match(line)
                if m:
                    ids.add(m.group(1).decode('latin-1'))
    return ids


# ------------------------------------------------------------------------------------------------ new engines (>= 7.5)
def attr_info_new(db, lay, a):
    """attribute record(s) of a part: printable ASCII strings (>= 3 chars) with their byte offsets in the record, and the
    'rest' record strings (Tekla stores the profile tail / name parts there). Raw evidence; offsets are engine specific."""
    if a is None or not lay.get('attr_stride'):
        return None
    out = []
    try:
        rr = db.attr_records(lay, a)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}
    for o in list(rr)[:2]:
        blob = db.b[o:o + lay['attr_stride']]
        rec = {'strings': [[mm.start(), mm.group().decode('latin-1')] for mm in ASCII.finditer(blob)
                           if re.search(rb'[A-Za-z0-9]', mm.group())]}
        try:
            ref = int(db.I([o + lay['rest_ref']])[0])
            rec['rest'] = [db.cstr(r + lay['rest_off'], 160) for r in list(db.lookup_all(ref) or [])[:2]]
        except Exception as e:
            rec['rest_error'] = f'{type(e).__name__}: {e}'
        out.append(rec)
    return out


def outline_new(db, lay, m):
    """contour outline of a record: the decoder's own polygon (chamfers applied) or its raw outline points. Local (u, v) in
    the record's (x, y) plane through O; world = O + x*u + y*v (the plane contour plates are centred on)"""
    src = None
    P = None
    err = None
    try:
        P = db.polygon(lay, m)
        src = 'db1 contour record (decoder polygon, chamfers applied)' if P else None
    except Exception as e:
        err = f'polygon: {type(e).__name__}: {e}'
    if not P:
        try:
            raw = db.outline_points(lay, m)
            if raw:
                P = [p[:2] for p in raw]
                src = 'db1 contour record (raw outline points, chamfers not applied)'
        except Exception as e:
            err = (err + '; ' if err else '') + f'outline_points: {type(e).__name__}: {e}'
    if not P:
        return None, None, None, err
    O, x, y = vec(m['O']), vec(m['x']), vec(m['y'])
    loc = [[float(p[0]), float(p[1])] for p in P]
    world = [[O[i] + x[i] * u + y[i] * v for i in range(3)] for u, v in loc]
    return loc, world, src, err


def frame_of(m):
    O, E, x, y = vec(m.get('O')), vec(m.get('E')), vec(m.get('x')), vec(m.get('y'))
    z = unit(cross(x, y)) if x and y else None
    return {'O': O, 'E': E, 'L': float(m['L']) if m.get('L') is not None else None, 'x': x, 'y': y, 'z': z}


def facts_new(C, plist, cat, mods, gid_of, in_step):
    db, lay, M = C['db'], C['lay'], C['M']
    section_for, zero_section = mods['db1step'].section_for, mods['db1step'].zero_section
    db1bolts = sys.modules.get('db1bolts')
    bym = {m['seq']: m for m in M}
    links = C.get('links') or {}
    inv = collections.defaultdict(list)
    for p, cs in links.items():
        for c in cs:
            inv[int(c)].append(int(p))
    pl = {p[0]: p for p in plist}
    cut_body = C.get('cut_body') or {}
    bseq = C.get('bseq') or {}
    errors = []
    skipped = []
    for p in plist:
        if p[3] != 'skipped':
            continue
        seq = p[0]
        r = {'record': seq, 'reason': p[4], 'category': p[2], 'profile': p[1]}
        m = bym.get(seq)
        g = bseq.get(seq)
        if m is not None:
            r['axis'] = frame_of(m)
            try:
                k, v, how = section_for(m['prof'], cat) if m.get('prof') else (None, 'no_profile', None)
                r['catalog_lookup'] = {'kind': k, 'result': v if k is None else how}
            except Exception as e:
                r['catalog_lookup'] = {'error': f'{type(e).__name__}: {e}'}
            r['profile_number_mm'] = profile_number(m.get('prof'))
            r['profile_is_bare_number'] = bool(m.get('prof') and re.fullmatch(r'\s*[\d.]+\s*', m['prof']))
            loc, world, src, err = outline_new(db, lay, m)
            r['outline_local'], r['outline_world'], r['outline_source'] = loc, world, src
            if err:
                r['outline_error'] = err
            r['attributes'] = attr_info_new(db, lay, m.get('attr'))
            r['cut_bodies_linked'] = sorted(int(c) for c in links.get(seq, []))
            pts = (world or []) + [r['axis']['O'], r['axis']['E']]
            r['bbox_world'] = bbox(pts)
            r['geometry_recorded'] = ('outline+profile_number' if world and r['profile_number_mm'] else
                                      'outline' if world else 'axis+profile' if m.get('prof') else 'axis_only')
        if g is not None:
            r['bolt_group'] = bolt_group_new(g, C, pl, gid_of, in_step, db1bolts)
            r['geometry_recorded'] = 'bolt_positions+axis+diameter+length'
            r['bbox_world'] = bbox([vec(w) for w in (g.get('world') or [])])
        if m is None and g is None:
            r['geometry_recorded'] = 'none'
            r['note'] = 'record not in the decoder member list (no geometry available)'
        skipped.append(r)
    # cut bodies
    cuts = []
    for m in M:
        if not m.get('cut'):
            continue
        seq = m['seq']
        built = seq in cut_body
        par = sorted(inv.get(seq, []))
        c = {'record': seq, 'profile': m.get('prof'), 'built': built,
             'unbuilt_reason': None if built else ('cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'),
             'parents': [{'record': q, 'written': bool(pl.get(q) and pl[q][3] == 'written'),
                          'gid': gid_of(pl[q]) if pl.get(q) else None} for q in par],
             'applied_to': sorted(q for q in par if built and pl.get(q) and pl[q][3] == 'written')}
        if not built:
            c['axis'] = frame_of(m)
            loc, world, src, err = outline_new(db, lay, m)
            c['outline_world'], c['outline_source'] = world, src
            c['profile_number_mm'] = profile_number(m.get('prof'))
        cuts.append(c)
    # fittings / line cuts decoded but not applied
    fits = []
    NOFIT = C.get('NOFIT') or set()
    FIT, LCUT = C.get('FIT') or {}, C.get('LCUT') or {}
    for m in M:
        if id(m) in NOFIT:
            q = pl.get(m['seq'])
            fits.append({'record': m['seq'], 'profile': m.get('prof'), 'gid': gid_of(q) if q else None,
                         'in_shipped_step': in_step(q) if q else None, 'axis': frame_of(m),
                         'fittings': [{'point': vec(P), 'normal': vec(n)} for P, n in FIT.get(m['seq'], [])],
                         'line_cuts': clean(LCUT.get(m['seq'], []))})
    groups = [bolt_group_new(g, C, pl, gid_of, in_step, db1bolts) for g in (C.get('bgroups') or [])]
    return skipped, cuts, fits, groups, errors


def bolt_flags(bl, db1bolts):
    live = [bb for bb in bl if not bb.get('holes_only')]
    wex = (lambda bb: db1bolts.washer_exact(bb)) if db1bolts and hasattr(db1bolts, 'washer_exact') else (lambda bb: None)
    W = lambda bb: (bb.get('wash_head') or 0) + (bb.get('wash_nut') or 0) + (bb.get('wash_2') or 0)
    return {'bolts': len(bl), 'holes_only': len(bl) - len(live),
            'nominal_head_nut': sum(1 for bb in live if not bb.get('std')),
            'tolerance_not_decoded': sum(1 for bb in live if bb.get('tol') is None),
            'axial_unknown_centred': sum(1 for bb in live if bb.get('head_up') is False),
            'axial_fitted_to_plies': sum(1 for bb in live if bb.get('head_up') and not bb.get('axial_decoded')),
            'washers': sum(W(bb) for bb in live),
            'washers_nominal': sum(W(bb) for bb in live if W(bb) and wex(bb) is False),
            'washer_side_inferred': sum(1 for bb in live if bb.get('wash_2'))}


def bolt_json(bb):
    std = bb.get('std') or {}
    return {'centre': vec(bb['c']) if bb.get('c') is not None else (vec(bb['p0']) if bb.get('p0') is not None else None),
            'axis': vec(bb['ez']) if bb.get('ez') is not None else None, 'd': bb.get('d'), 'L': bb.get('L'),
            'holes_only': bool(bb.get('holes_only')), 'standard_family': std.get('family'), 'standard_source': std.get('source'),
            'head_up': bb.get('head_up'), 'axial_decoded': bb.get('axial_decoded'), 'axial': bb.get('axial'),
            'washers': [bb.get('wash_head') or 0, bb.get('wash_2') or 0, bb.get('wash_nut') or 0], 'nuts': bb.get('nuts'),
            'tolerance': bb.get('tol'), 'grip': clean(bb.get('grip'))}


def bolt_group_new(g, C, pl, gid_of, in_step, db1bolts):
    seq = g['seq']
    BG = C.get('BG') or {}
    blinks = C.get('blinks') or {}
    V2SLOT = C.get('V2SLOT') or {}
    V2ROT = C.get('V2ROT') or {}
    bl = BG.get(seq) or []
    q = pl.get(seq)
    sx, sy = abs(g.get('slot_x') or 0), abs(g.get('slot_y') or 0)
    plies = [int(p) for p in (blinks.get(seq) or [])]
    if not (sx or sy):
        dec = 'not_slotted'
    elif seq not in V2SLOT:
        dec = 'not_evaluated'
    elif V2SLOT[seq] is None:
        dec = 'undecided_holes_cut_round'
    else:
        dec = 'decoded'
    sd = V2SLOT.get(seq) or {}
    return clean({
        'record': seq, 'written_as': (q[4] if q[3] == 'written' else 'skipped:' + q[4]) if q else 'not_in_parts_list',
        'gid': gid_of(q) if q else None, 'in_shipped_step': in_step(q) if q else None, 'profile': g.get('prof'),
        'standard': g.get('standard'), 'd': g.get('d'), 'L': g.get('L'), 'tolerance': g.get('tol'), 'count': g.get('count'),
        'O': vec(g['O']) if g.get('O') is not None else None, 'x': vec(g['x']) if g.get('x') is not None else None,
        'y': vec(g['y']) if g.get('y') is not None else None, 'z': vec(g['z']) if g.get('z') is not None else None,
        'positions_world': [vec(w) for w in (g.get('world') or [])],
        'plies': [{'record': p, 'gid': gid_of(pl[p]) if pl.get(p) else None,
                   'written': bool(pl.get(p) and pl[p][3] == 'written'),
                   'slotted': (bool(sd.get(p)) if dec == 'decoded' else None),
                   'slot_rotated': bool((V2ROT.get(seq) or {}).get(p)) if dec == 'decoded' else None} for p in plies],
        'slot': {'slot_x': sx, 'slot_y': sy, 'slot_parts_mask': g.get('slot_parts'), 'rotate_slots': g.get('slot_rot'),
                 'decision': dec},
        'flags': bolt_flags(bl, db1bolts), 'bolts': [bolt_json(bb) for bb in bl]})


# ------------------------------------------------------------------------------------------------ old engines (< 7.5)
def facts_old(C, plist, cat, mods, gid_of, in_step):
    M = C['M']
    section_for, zero_section = mods['db1step'].section_for, mods['db1step'].zero_section
    db1bolts = sys.modules.get('db1bolts')
    bym = {m['pid']: m for m in M}
    pl = {p[0]: p for p in plist}
    cut_rel = C.get('cut_rel') or {}
    inv = collections.defaultdict(list)
    for p, cs in cut_rel.items():
        for c in cs:
            inv[int(c)].append(int(p))
    cut_body = C.get('cut_body') or {}
    errors = []

    def outline_old(m):
        poly = m.get('old_poly')
        if not poly or len(poly) < 3:
            return None, None
        O, xr, y = vec(m['O']), vec(m['xr']), vec(m['y'])
        z = cross(xr, y)
        useZ = m.get('form') == 2
        loc = [[float(q[0]), float(q[1])] + ([float(q[2])] if useZ and len(q) > 2 else []) for q in poly]
        world = [[O[i] + xr[i] * q[0] + y[i] * q[1] + (z[i] * q[2] if useZ and len(q) > 2 else 0.0) for i in range(3)] for q in loc]
        return loc, world

    def old_frame(m):
        f = frame_of(m)
        f['xr'] = vec(m.get('xr'))
        f['sgn'] = m.get('sgn')
        return f

    skipped = []
    for p in plist:
        if p[3] != 'skipped':
            continue
        seq = p[0]
        r = {'record': seq, 'reason': p[4], 'category': p[2], 'profile': p[1]}
        m = bym.get(seq)
        if m is not None:
            r['axis'] = old_frame(m)
            try:
                k, v, how = section_for(m['prof'], cat) if m.get('prof') else (None, 'no_profile', None)
                r['catalog_lookup'] = {'kind': k, 'result': v if k is None else how}
            except Exception as e:
                r['catalog_lookup'] = {'error': f'{type(e).__name__}: {e}'}
            r['profile_number_mm'] = profile_number(m.get('prof'))
            r['profile_is_bare_number'] = bool(m.get('prof') and re.fullmatch(r'\s*[\d.]+\s*', m['prof']))
            loc, world = outline_old(m)
            r['outline_local'], r['outline_world'] = loc, world
            r['outline_source'] = (None if not world else
                                   'db1 polybeam / arc points (old engine, form 4: points ALONG the member, not an outline)'
                                   if m.get('form') == 4 else
                                   'db1 part polygon (old engine, part csys; plane z used when form == 2)')
            r['attributes'] = {'material': m.get('mat'), 'name': m.get('ben'), 'obj_type': m.get('obj_type'), 'form': m.get('form')}
            r['cut_bodies_linked'] = sorted(int(c) for c in cut_rel.get(seq, []))
            r['bbox_world'] = bbox((world or []) + [r['axis']['O'], r['axis']['E']])
            r['geometry_recorded'] = ('outline+profile_number' if world and r['profile_number_mm'] else
                                      'outline' if world else 'axis+profile' if m.get('prof') else 'axis_only')
            if m.get('bolt'):
                r['bolt_group'] = group_old(seq, C, pl, gid_of, in_step, db1bolts)
                r['geometry_recorded'] = 'bolt_positions+axis+diameter+length'
        else:
            r['geometry_recorded'] = 'none'
            r['note'] = 'record not in the decoder member list (no geometry available)'
        skipped.append(r)
    cuts = []
    for m in M:
        if not m.get('cut'):
            continue
        seq = m['pid']
        built = seq in cut_body
        par = sorted(inv.get(seq, []))
        c = {'record': seq, 'profile': m.get('prof'), 'material': m.get('mat'), 'built': built,
             'unbuilt_reason': None if built else ('cut_body_zero_thickness' if zero_section(m.get('prof')) else 'cut_body_unbuilt'),
             'parents': [{'record': q, 'written': bool(pl.get(q) and pl[q][3] == 'written'),
                          'gid': gid_of(pl[q]) if pl.get(q) else None} for q in par],
             'applied_to': sorted(q for q in par if built and pl.get(q) and pl[q][3] == 'written')}
        if not built:
            c['axis'] = old_frame(m)
            c['outline_world'] = outline_old(m)[1]
            c['profile_number_mm'] = profile_number(m.get('prof'))
        cuts.append(c)
    fits = []
    NOFIT = C.get('NOFIT') or set()
    for m in M:
        if id(m) in NOFIT:
            q = pl.get(m['pid'])
            fits.append({'record': m['pid'], 'profile': m.get('prof'), 'gid': gid_of(q) if q else None,
                         'in_shipped_step': in_step(q) if q else None, 'axis': old_frame(m)})
    groups = [group_old(m['pid'], C, pl, gid_of, in_step, db1bolts) for m in M if m.get('bolt') and not m.get('cut')]
    return skipped, cuts, fits, groups, errors


def old_bolt_index(C):
    """once per model: group pid -> its bolts (BL order) and -> {ply pid: holes} (the parts the converter cut holes in)"""
    BL = C.get('BL') or []
    inside = C.get('inside') or {}
    by_group = collections.defaultdict(list)
    for bb in BL:
        by_group[bb.get('pid')].append(bb)
    plies = collections.defaultdict(collections.OrderedDict)
    for m in C.get('M') or []:
        for i in (C.get('part_bolts') or {}).get(id(m), []):
            if (id(m), i) in inside:
                continue
            g = BL[i].get('pid')
            plies[g][m['pid']] = plies[g].get(m['pid'], 0) + 1
    return by_group, plies


def group_old(pid, C, pl, gid_of, in_step, db1bolts):
    if '_bolt_index' not in C:
        C['_bolt_index'] = old_bolt_index(C)
    by_group, plies_by_group = C['_bolt_index']
    SLOT_SET = C.get('SLOT_SET') or {}
    SLOTS_ON = bool(C.get('SLOTS_ON'))
    ROTP = C.get('ROTP') or {}
    bl = by_group.get(pid) or []
    plies = plies_by_group.get(pid) or {}
    slotted = any(any(abs(float(x)) > 1e-9 for x in (bb.get('slot') or ())) for bb in bl)
    if not slotted:
        dec = 'not_slotted'
    elif not SLOTS_ON:
        dec = 'undecided_holes_cut_round'          # slot decoding off for this engine: every hole of the group cut round
    elif SLOT_SET.get(pid, False) is None:
        dec = 'undecided_holes_cut_round'
    elif pid in SLOT_SET:
        dec = 'decoded'
    else:
        dec = 'not_evaluated'
    sd = SLOT_SET.get(pid) or {}
    q = pl.get(pid)
    b0 = bl[0] if bl else {}
    return clean({
        'record': pid, 'written_as': (q[4] if q[3] == 'written' else 'skipped:' + q[4]) if q else 'not_in_parts_list',
        'gid': gid_of(q) if q else None, 'in_shipped_step': in_step(q) if q else None,
        'standard': b0.get('standard'), 'd': b0.get('d'), 'L': b0.get('L'),
        'positions_world': [vec(bb['c']) for bb in bl if bb.get('c') is not None],
        'plies': [{'record': p, 'holes': n, 'gid': gid_of(pl[p]) if pl.get(p) else None,
                   'written': bool(pl.get(p) and pl[p][3] == 'written'),
                   'slotted': (bool(sd.get(p)) if dec == 'decoded' else None),
                   'slot_rotated': bool((ROTP.get(pid) or {}).get(p)) if dec == 'decoded' else None} for p, n in plies.items()],
        'slot': {'slot': clean(b0.get('slot')), 'slot_state': b0.get('slot_state'), 'slot_engine_on': SLOTS_ON, 'decision': dec},
        'flags': bolt_flags(bl, db1bolts), 'bolts': [bolt_json(bb) for bb in bl]})


# ------------------------------------------------------------------------------------------------ main
def main():
    cfg = json.load(open(sys.argv[1]))
    out = cfg['out']
    work = tempfile.mkdtemp(prefix='facts_', dir=os.path.dirname(os.path.abspath(out)))
    res = {'schema': SCHEMA, 'model_id': cfg['model_id'], 'kit': cfg['kit'], 'code': cfg['code'],
           'units': 'mm; world coordinates = the decoder model coordinates, the same frame the converter wrote into the IFC '
                    'and the shipped STEP (IfcSite placement is the identity)',
           'conventions': {
               'record': 'DB1 record id (decoder seq for engines >= 7.5, part id for older engines) = parts[][0]',
               'reason': "the converter's own skip reason (db1step parts list), e.g. unresolved = profile string not in the "
                         'catalog, contour_plate_no_outline, implausible_profile, no_profile, bolt_group_unplaced',
               'axis': 'O, E = start / end of the record reference line, L = recorded length, x / y = record frame '
                       '(contour plates: outline plane), z = x cross y',
               'outline_world': 'contour points on the record plane (O + x*u + y*v). The converter centres contour plates on '
                                'this plane: extrusion from -t/2 to +t/2 along z',
               'profile_number_mm': "first number in the profile string = the converter's contour-plate thickness rule "
                                    "(float(re.findall('[\\d.]+', profile)[0])); a candidate, not a decoded thickness field",
               'gid': 'GlobalId in source/model.ifc; equal to the shipped STEP PRODUCT id when in_shipped_step is true',
               'bolt_groups.slot.decision': 'undecided_holes_cut_round = the group is slotted in the DB1 but the converter '
                                            'could not decide which plies Tekla slots: every ply got ROUND holes'}}
    try:
        st, CAP, cat, db1step = capture(cfg['kit_dir'], cfg['db1'], cfg['layout'], cfg.get('variants'), bool(cfg.get('full_discovery')), work)
        res['decoder_status'] = st.get('status') if isinstance(st, dict) else None
        plist = (st or {}).pop('parts_list', None) if isinstance(st, dict) else None
        path = 'old' if 'old' in CAP else ('new' if 'new' in CAP and 'M' in CAP['new'] else None)
        res['decoder_path'] = {'old': 'old engine (db1step.convert_old)', 'new': 'record-discovered engine (db1step._convert)'}.get(path)
        res['engine'] = cfg.get('engine')
        if plist is None or path is None:
            raise RuntimeError(f'converter returned status {res["decoder_status"]!r} without a parts list / captured state')
        # proofs: this decode == the reproducing decode == the conversion fleet's decode (every field but the GlobalId)
        proof = {}
        repro = None
        if cfg.get('repro_parts') and os.path.exists(cfg['repro_parts']):
            repro = json.load(gzip.open(cfg['repro_parts'], 'rt'))
            proof['parts_list_vs_reproducing_run'] = compare_plists(plist, repro)
        fleet = None
        if cfg.get('fleet_decoded_parts') and os.path.exists(cfg['fleet_decoded_parts']):
            fleet = json.load(gzip.open(cfg['fleet_decoded_parts'], 'rt'))
            proof['parts_list_vs_conversion_fleet'] = compare_plists(plist, fleet)
        ship = shipped_product_ids(cfg['shipped_step'])
        gmap = json.load(open(cfg['gid_map'])) if cfg.get('gid_map') and os.path.exists(cfg['gid_map']) else None
        # GlobalId per parts-list entry: reproducing run's GlobalId -> final IFC GlobalId (restore map); without a reproduction
        # the fleet's original GlobalIds (= shipped STEP PRODUCT ids for the products the STEP kept)
        if repro is not None and gmap is not None and proof['parts_list_vs_reproducing_run']['equal']:
            gsrc = [gmap.get(p[5]) if p[5] else None for p in repro]
            proof['gid_source'] = 'reproducing run GlobalIds mapped through the restore map (source/model.ifc GlobalIds)'
        elif fleet is not None and proof['parts_list_vs_conversion_fleet']['equal']:
            gsrc = [p[5] for p in fleet]
            proof['gid_source'] = 'conversion fleet decoded_parts GlobalIds (original conversion run)'
        else:
            gsrc = [None] * len(plist)
            proof['gid_source'] = 'none (no proven reference parts list)'
        gid_by_seq = {}
        for p, g in zip(plist, gsrc):
            gid_by_seq[(p[0], p[3], p[4])] = g
        gid_of = lambda q: gid_by_seq.get((q[0], q[3], q[4]))
        in_step = lambda q: (gid_of(q) in ship) if gid_of(q) else False
        if fleet is not None and gsrc and proof['gid_source'].startswith('reproducing'):
            fl = {(p[0], p[3], p[4]): p[5] for p in fleet if p[5]}
            both = [(k, g) for k, g in gid_by_seq.items() if g and fl.get(k) and k in fl]
            proof['gids_vs_conversion_fleet'] = {'compared': len(both), 'equal': sum(1 for k, g in both if fl[k] == g),
                                                 'note': 'fleet GlobalIds of products the shipped STEP kept must equal ours'}
            kept = [(k, g) for k, g in both if g in ship]
            proof['gids_vs_conversion_fleet'].update(compared_in_step=len(kept), equal_in_step=sum(1 for k, g in kept if fl[k] == g))
        written = [p for p in plist if p[3] == 'written' and p[4] not in ('holes_only_group',)]
        proof['written_products_in_shipped_step'] = sum(1 for p in written if in_step(p))
        proof['written_products'] = len(written)
        proof['shipped_step_products'] = len(ship)
        comps = [v['equal'] for k, v in proof.items() if k.startswith('parts_list_vs')]
        res['usable_for_red_parts'] = bool(comps) and all(comps)
        res['proof'] = clean(proof)
        mods = {'db1step': db1step}
        if path == 'new':
            sk, cuts, fits, groups, errs = facts_new(CAP['new'], plist, cat, mods, gid_of, in_step)
        else:
            sk, cuts, fits, groups, errs = facts_old(CAP['old'], plist, cat, mods, gid_of, in_step)
        # parts the decoder wrote into the IFC whose product the STEP stage dropped
        dropped = []
        if proof['gid_source'] != 'none (no proven reference parts list)':
            for p in written:
                g = gid_of(p)
                if g and g not in ship:
                    dropped.append({'record': p[0], 'profile': p[1], 'category': p[2], 'how': p[4], 'gid': g,
                                    'note': 'written by the decoder into source/model.ifc (geometry there), absent from the '
                                            'shipped STEP'})
        cs = st.get('bolt_stats') or {}
        und = [g for g in groups if (g.get('slot') or {}).get('decision') == 'undecided_holes_cut_round']
        res['counts'] = {
            'parts_list': len(plist), 'written': sum(1 for p in plist if p[3] == 'written'),
            'skipped': len(sk), 'skipped_by_reason': dict(sorted(collections.Counter(p[4] for p in plist if p[3] == 'skipped').items())),
            'skipped_with_outline': sum(1 for r in sk if r.get('outline_world')),
            'dropped_by_step_writer': len(dropped),
            'cut_bodies': len(cuts), 'cut_bodies_unbuilt': sum(1 for c in cuts if not c['built']),
            'cut_bodies_unbuilt_with_written_parent': sum(1 for c in cuts if not c['built'] and any(q['written'] for q in c['parents'])),
            'fittings_not_applied_parts': len(fits),
            'bolt_groups': len(groups),
            'slotted_groups_holes_cut_round': len(und),
            'bolts_in_slotted_groups_cut_round': sum(len(g.get('bolts') or []) for g in und),
            'plies_with_round_holes_for_slots': len({q['record'] for g in und for q in g.get('plies') or [] if q.get('written')}),
            'converter_bolt_stats_slotted_bolts_cut_round': cs.get('slotted_bolts_cut_round'),
            'converter_bolt_stats_holes_in_slotted_groups_cut_round': cs.get('holes_in_slotted_groups_cut_round'),
            'converter_fittings_parts_not_applied': (st.get('fittings') or {}).get('parts_not_applied')}
        res['converter_stats'] = clean({k: st.get(k) for k in ('skipped', 'sources', 'written', 'members', 'cut_stats', 'fittings',
                                                               'cuts_applied', 'axis_mismatch_dropped')})
        res['converter_stats']['bolt_stats'] = clean({k: v for k, v in cs.items() if not isinstance(v, (dict, list))})
        res['skipped'] = clean(sk)
        res['dropped_by_step_writer'] = clean(dropped)
        res['cut_bodies'] = clean(cuts)
        res['fittings_not_applied'] = clean(fits)
        res['bolt_groups'] = clean(groups)
        res['parts'] = clean([[p[0], p[1], p[2], p[3], p[4], gid_of(p), in_step(p) if p[3] == 'written' else None,
                               p[6] if len(p) > 6 else None] for p in plist])
        res['parts_columns'] = ['record', 'profile', 'category', 'status', 'how_or_reason', 'gid', 'in_shipped_step', 'n_cuts']
        if errs:
            res['errors'] = errs
        res['status'] = 'ok' if res['usable_for_red_parts'] else 'inconsistent'
    except Exception as e:
        res['status'] = 'failed'
        res['usable_for_red_parts'] = False
        res['error'] = f'{type(e).__name__}: {e}'
        res['trace'] = traceback.format_exc()[-3000:]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with open(out + '.tmp', 'w') as f:
        json.dump(res, f, indent=None, sort_keys=True, separators=(',', ':'))
        f.write('\n')
    os.replace(out + '.tmp', out)
    print(json.dumps({'status': res['status'], 'usable_for_red_parts': res.get('usable_for_red_parts'),
                      'counts': res.get('counts'), 'error': res.get('error')}), flush=True)


if __name__ == '__main__':
    main()
