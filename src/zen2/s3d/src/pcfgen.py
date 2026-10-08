"""Pipeline JSON (s3d-pipeline/1) -> PCF text + validation stats.

Coordinates in MM (S3D metres x 1000), bores in MM (DN). Records: PIPE, ELBOW/BEND, TEE, OLET, REDUCER-*,
FLANGE, FLANGE-BLIND, VALVE, INSTRUMENT, CAP, COUPLING, UNION, FILTER, MISC-COMPONENT, GASKET, BOLT, WELD,
SUPPORT, END-CONNECTION-PIPELINE / END-CONNECTION-EQUIPMENT, MATERIALS.
"""
import math, collections

TOL_MM = 1.0


def P(x):
    return '%.2f %.2f %.2f' % (x[0] * 1000.0, x[1] * 1000.0, x[2] * 1000.0)


def B(b):
    if b is None:
        return '0'
    return ('%.1f' % b).rstrip('0').rstrip('.')


def _dirword(v, tol_deg=10.0):
    n = math.sqrt(sum(a * a for a in v))
    if n < 1e-9:
        return None
    v = [a / n for a in v]
    words = [((1, 0, 0), 'EAST'), ((-1, 0, 0), 'WEST'), ((0, 1, 0), 'NORTH'), ((0, -1, 0), 'SOUTH'), ((0, 0, 1), 'UP'), ((0, 0, -1), 'DOWN')]
    best = max(words, key=lambda w: sum(a * b for a, b in zip(v, w[0])))
    return best[1] if sum(a * b for a, b in zip(v, best[0])) >= math.cos(math.radians(tol_deg)) else None


def _clean(s, n=110):
    if s is None:
        return None
    s = str(s).replace('\r', ' ').replace('\n', ' ').replace('\t', ' ').strip()
    if s.lower() in ('undefined', 'none', 'null', 'n/a', '-'):
        return None
    return s[:n] if s else None


def to_pcf(J):
    L = []
    w = L.append
    stats = collections.Counter()
    mats = collections.OrderedDict()
    pts = []          # (kind, xyz_mm, bore, comp_index, type)

    def mat_id(C):
        code = C.get('item_code') or C.get('part_number') or C.get('catalog_part')
        if not code:
            return None, None
        code = _clean(code, 80)
        if code not in mats:
            mats[code] = (len(mats) + 1, _clean(C.get('description'), 200), C.get('material'))
        return code, mats[code][0]

    w('ISOGEN-FILES ISOGEN.FLS')
    w('UNITS-BORE MM')
    w('UNITS-CO-ORDS MM')
    w('UNITS-WEIGHT KGS')
    w('UNITS-BOLT-DIA MM')
    w('UNITS-BOLT-LENGTH MM')
    w('PIPELINE-REFERENCE %s' % (_clean(J.get('name'), 100) or J['source']['oid']))
    w('    PROJECT-IDENTIFIER MLNG@1')
    w('    AREA %s' % _clean(J.get('area'), 100))
    if J.get('specs'):
        w('    PIPING-SPEC %s' % _clean(J['specs'][0], 60))
    if _clean(J.get('fluid_code')):
        w('    ATTRIBUTE1 %s' % _clean(J['fluid_code']))
    w('    ATTRIBUTE2 %s' % _clean('/'.join(J.get('system_path') or []), 200))
    w('    ATTRIBUTE3 %s' % J['source']['oid'])
    ins = [r for r in J.get('runs', []) if r.get('insulated')]
    if ins and ins[0].get('insulation_thickness'):
        w('    INSULATION-SPEC %s' % B(ins[0]['insulation_thickness'] * 1000.0))

    conn_xyz = {e['oid']: e['xyz'] for e in J.get('connections', []) if e.get('xyz')}
    conn_bores = collections.defaultdict(list)
    for C0 in J['components']:
        for q in C0['ports']:
            if q.get('conn') and q.get('bore_mm'):
                conn_bores[q['conn']].append((C0['oid'], q['bore_mm']))
    ci = 0
    for C in J['components']:
        t = C['pcf_type']
        ports = {}
        for q in C['ports']:
            # S3D models slip-on / socket insertion and gasket gaps as a set-back of the port from the
            # connection point; PCF wants coincident points, so snap set-backs <= 12 mm to the connection
            cx = conn_xyz.get(q.get('conn'))
            if cx and q.get('xyz'):
                g = math.dist(cx, q['xyz'])
                if 1e-6 < g <= 0.012:
                    q = dict(q, xyz=cx)
                    stats['setback_snapped'] += 1
            ports[q['index']] = q
        C = dict(C, ep1=ports.get(1, {}).get('xyz') or C.get('ep1'), ep2=ports.get(2, {}).get('xyz') or C.get('ep2'),
                 ep3=ports.get(3, {}).get('xyz') or C.get('ep3'))
        ep = [(i, ports[i]) for i in sorted(ports) if ports[i].get('xyz') and i in (1, 2)]
        b1 = C.get('bore1_mm'); b2 = C.get('bore2_mm') or b1
        body = []
        geom_ok = True
        if t == 'OLET':
            hp = C.get('header_point') or C.get('cp') or C.get('ep1')
            if hp and C.get('ep2'):
                body.append('    CENTRE-POINT %s' % P(hp))
                body.append('    BRANCH1-POINT %s %s' % (P(C['ep2']), B(ports.get(2, {}).get('bore_mm') or b2)))
                pts.append(('BP', C['ep2'], ports.get(2, {}).get('bore_mm') or b2, ci, t))
                pts.append(('HP', C['ep1'], None, ci, t))
            else:
                geom_ok = False
        else:
            for i, q in ep:
                body.append('    END-POINT %s %s' % (P(q['xyz']), B(q.get('bore_mm') or (b1 if i == 1 else b2))))
                pts.append(('EP', q['xyz'], q.get('bore_mm') or (b1 if i == 1 else b2), ci, t))
            need = {'PIPE': 2, 'PIPE-FIXED': 2, 'ELBOW': 2, 'BEND': 2, 'TEE': 2, 'REDUCER-CONCENTRIC': 2, 'REDUCER-ECCENTRIC': 2,
                    'FLANGE': 2, 'VALVE': 2, 'INSTRUMENT': 2, 'COUPLING': 2, 'UNION': 2, 'FILTER': 2}.get(t, 1)
            need = min(need, max(1, len([i for i in ports if i in (1, 2)])))
            if len(ep) < need:
                if len(ep) == 0:
                    geom_ok = False
                else:
                    stats['comp_missing_endpoint'] += 1
            if t in ('ELBOW', 'BEND', 'TEE', 'VALVE', 'INSTRUMENT', 'FILTER') and C.get('cp'):
                body.append('    CENTRE-POINT %s' % P(C['cp']))
            elif t in ('ELBOW', 'BEND', 'TEE'):
                stats['comp_missing_centre'] += 1
            if t == 'TEE':
                if C.get('ep3'):
                    bb = ports.get(3, {}).get('bore_mm') or b2
                    body.append('    BRANCH1-POINT %s %s' % (P(C['ep3']), B(bb)))
                    pts.append(('BP', C['ep3'], bb, ci, t))
                else:
                    stats['tee_missing_branch'] += 1
            elif C.get('ep3') and t in ('FLANGE', 'VALVE', 'INSTRUMENT', 'MISC-COMPONENT'):
                bb = ports.get(3, {}).get('bore_mm')
                body.append('    BRANCH1-POINT %s %s' % (P(C['ep3']), B(bb)))
                pts.append(('BP', C['ep3'], bb, ci, t))
        if not geom_ok:
            stats['comp_skipped_no_points'] += 1
            continue
        w(t)
        L.extend(body)
        if C.get('skey'):
            w('    SKEY %s' % C['skey'])
        if t in ('ELBOW', 'BEND') and C.get('bend'):
            if C['bend'].get('angle_deg') is not None:
                w('    ANGLE %d' % round(C['bend']['angle_deg'] * 100))
            if C['bend'].get('radius'):
                w('    BEND-RADIUS %s' % B(C['bend']['radius'] * 1000.0))
        if t == 'REDUCER-ECCENTRIC' and C.get('ep1') and C.get('ep2'):
            # flat side = direction from the big-end centre to the small-end centre, perpendicular to the axis
            q1, q2 = ports.get(1, {}), ports.get(2, {})
            big, small = (C['ep1'], C['ep2']) if (q1.get('od') or 0) >= (q2.get('od') or 0) else (C['ep2'], C['ep1'])
            M = C.get('matrix')
            if M:
                ax = M[0:3]
            else:
                ax = [small[k] - big[k] for k in range(3)]
            n = math.sqrt(sum(a * a for a in ax)) or 1.0
            ax = [a / n for a in ax]
            d = [small[k] - big[k] for k in range(3)]
            dp = sum(d[k] * ax[k] for k in range(3))
            off = [d[k] - dp * ax[k] for k in range(3)]
            fd = _dirword(off, 20) if math.sqrt(sum(a * a for a in off)) > 1e-5 else None
            if fd:
                w('    FLAT-DIRECTION %s' % fd)
        if t == 'VALVE' and C.get('matrix'):
            fd = _dirword(C['matrix'][3:6], 15)
            if fd:
                w('    SPINDLE-DIRECTION %s' % fd)
        code, mid = mat_id(C)
        if code:
            w('    ITEM-CODE %s' % code)
            w('    MATERIAL-IDENTIFIER %d' % mid)
        if t == 'PIPE' and C.get('cut_length'):
            w('    COMPONENT-ATTRIBUTE10 %s' % B(C['cut_length'] * 1000.0))
        if C.get('weight') and t != 'PIPE':
            w('    WEIGHT %.3f' % C['weight'])
        if C.get('tag') and t in ('VALVE', 'INSTRUMENT', 'MISC-COMPONENT'):
            w('    TAG %s' % _clean(C['tag'], 60))
        if _clean(C.get('name')) and t != 'PIPE':
            w('    COMPONENT-ATTRIBUTE1 %s' % _clean(C['name'], 80))
        if _clean(C.get('material')):
            w('    COMPONENT-ATTRIBUTE2 %s' % _clean(C['material'], 80))
        if _clean(C.get('schedule1')):
            w('    COMPONENT-ATTRIBUTE3 %s' % _clean(C['schedule1'], 30))
        w('    UCI %s' % C['oid'])
        stats['comp_' + t] += 1
        ci += 1
        if t == 'PIPE' and C.get('ep1') and C.get('ep2'):
            # stub-in branches: header pipe ports 3..n
            a = C['ep1']; d = [C['ep2'][k] - a[k] for k in range(3)]; L2 = sum(v * v for v in d)
            for i in sorted(ports):
                q = ports[i]
                if i < 3 or not q.get('xyz') or L2 < 1e-12:
                    continue
                tt = sum((q['xyz'][k] - a[k]) * d[k] for k in range(3)) / L2
                cpt = [a[k] + d[k] * tt for k in range(3)]
                w('TEE-STUB')
                w('    CENTRE-POINT %s' % P(cpt))
                bb = min([b for o, b in conn_bores.get(q.get('conn'), []) if o != C['oid']] or [q.get('bore_mm') or 0]) or None
                w('    BRANCH1-POINT %s %s' % (P(q['xyz']), B(bb)))
                w('    SKEY TESO')
                w('    UCI %s-P%d' % (C['oid'], i))
                pts.append(('BP', q['xyz'], bb, ci, 'TEE-STUB'))
                ci += 1
                stats['comp_TEE-STUB'] += 1

    # connection items and end connections
    bore_at = {}
    for kind, x, b, i, t in pts:
        bore_at[tuple(round(v * 1000.0) for v in x)] = b
    for e in J.get('connections', []):
        if not e.get('xyz'):
            continue
        key = tuple(round(v * 1000.0) for v in e['xyz'])
        bb = bore_at.get(key)
        for it in e.get('items', []):
            k = it['kind']
            if k == 'WELD':
                wt = (it.get('weld_type') or '').lower()
                w('WELD')
                w('    END-POINT %s %s' % (P(it.get('xyz') or e['xyz']), B(bb)))
                w('    END-POINT %s %s' % (P(it.get('xyz') or e['xyz']), B(bb)))
                w('    SKEY %s' % ('WF' if 'field' in wt else 'WW'))
                if it.get('weld_type'):
                    w('    COMPONENT-ATTRIBUTE1 %s' % _clean(it['weld_type']))
                w('    UCI %s' % it['oid'])
                stats['item_WELD'] += 1
            elif k == 'GASKET':
                w('GASKET')
                w('    END-POINT %s %s' % (P(e['xyz']), B(bb)))
                w('    END-POINT %s %s' % (P(e['xyz']), B(bb)))
                w('    SKEY GK')
                code = _clean(it.get('item_code'), 80) or ('GASKET-%s' % B(bb) if it.get('description') else None)
                if code:
                    if code not in mats:
                        mats[code] = (len(mats) + 1, _clean(it.get('description'), 200), None)
                    w('    ITEM-CODE %s' % code)
                    w('    MATERIAL-IDENTIFIER %d' % mats[code][0])
                w('    UCI %s' % it['oid'])
                stats['item_GASKET'] += 1
            elif k == 'BOLT':
                w('BOLT')
                w('    CO-ORDS %s %s' % (P(e['xyz']), B(bb)))
                if it.get('dia'):
                    w('    BOLT-DIA %s' % B(it['dia'] * 1000.0))
                if it.get('length'):
                    w('    BOLT-LENGTH %s' % B(it['length'] * 1000.0))
                if it.get('quantity'):
                    w('    BOLT-QUANTITY %d' % it['quantity'])
                if it.get('description'):
                    code = 'BOLT-' + ('%s-%s' % (B((it.get('dia') or 0) * 1000.0), B((it.get('length') or 0) * 1000.0)))
                    if code not in mats:
                        mats[code] = (len(mats) + 1, _clean(it.get('description'), 200), None)
                    w('    ITEM-CODE %s' % code)
                    w('    MATERIAL-IDENTIFIER %d' % mats[code][0])
                w('    UCI %s' % it['oid'])
                stats['item_BOLT'] += 1
        for x in e.get('external', []):
            if x['kind'] == 'PIPELINE' and x.get('pipeline'):
                w('END-CONNECTION-PIPELINE')
                w('    CO-ORDS %s %s' % (P(e['xyz']), B(bb)))
                w('    PIPELINE-REFERENCE %s' % _clean(x['pipeline'], 100))
                stats['end_conn_pipeline'] += 1
            elif x['kind'] == 'EQUIPMENT':
                w('END-CONNECTION-EQUIPMENT')
                w('    CO-ORDS %s %s' % (P(e['xyz']), B(bb)))
                w('    CONNECTION-REFERENCE %s' % _clean('%s/%s' % (x.get('equipment') or '', x.get('nozzle') or ''), 100))
                stats['end_conn_equipment'] += 1
    for s in J.get('supports', []):
        if not s.get('xyz'):
            stats['support_no_coords'] += 1
            continue
        w('SUPPORT')
        w('    CO-ORDS %s %s' % (P(s['xyz']), B(s.get('bore_mm'))))
        w('    SKEY 01HG')
        if s.get('catalog_assembly'):
            w('    ITEM-CODE %s' % _clean(s['catalog_assembly'], 80))
        if s.get('name'):
            w('    NAME %s' % _clean(s['name'], 60))
        if s.get('bom'):
            w('    COMPONENT-ATTRIBUTE1 %s' % _clean(s['bom'], 100))
        w('    UCI %s' % s['oid'])
        stats['support'] += 1
    if mats:
        w('MATERIALS')
        for code, (mid, desc, mg) in mats.items():
            w('MATERIAL-IDENTIFIER %d' % mid)
            w('    ITEM-CODE %s' % code)
            w('    DESCRIPTION %s' % (desc or code))
            if mg:
                w('    MATERIAL-GRADE %s' % _clean(mg, 80))

    # ---- validation in PCF space: every END-POINT must meet another component point, or be an open/external end
    grid = collections.defaultdict(list)
    for j, (kind, x, b, i, t) in enumerate(pts):
        grid[tuple(int(round(v * 1000.0)) for v in x)].append(j)
    ext_pts = set()
    for e in J.get('connections', []):
        if e.get('xyz') and e.get('external'):
            ext_pts.add(tuple(int(round(v * 1000.0)) for v in e['xyz']))
    open_conn = set()
    for e in J.get('connections', []):
        if e.get('xyz') and len(e.get('parts') or []) <= 1 and not e.get('external'):
            open_conn.add(tuple(int(round(v * 1000.0)) for v in e['xyz']))
    for C in J['components']:
        for q in C['ports']:
            if q.get('xyz') and not q.get('conn'):
                open_conn.add(tuple(int(round(v * 1000.0)) for v in q['xyz']))
    dangling = bore_bad = matched = 0
    for j, (kind, x, b, i, t) in enumerate(pts):
        if kind == 'HP':
            continue
        k = tuple(int(round(v * 1000.0)) for v in x)
        cands = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for jj in grid.get((k[0] + dx, k[1] + dy, k[2] + dz), []):
                        if pts[jj][3] != i:
                            cands.append(jj)
        cands = [jj for jj in cands if math.dist([v * 1000 for v in pts[jj][1]], [v * 1000 for v in x]) <= TOL_MM]
        if cands:
            matched += 1
            if b and any(pts[jj][2] and abs(pts[jj][2] - b) > 0.5 for jj in cands if pts[jj][0] != 'HP'):
                bore_bad += 1
        elif k not in ext_pts and k not in open_conn:
            dangling += 1
    stats['points'] = len(pts)
    stats['points_matched'] = matched
    stats['points_dangling'] = dangling
    stats['points_bore_mismatch'] = bore_bad
    stats['materials'] = len(mats)
    stats['lines'] = len(L)
    return '\n'.join(L) + '\n', dict(stats)
