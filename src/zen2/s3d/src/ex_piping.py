"""Piping extraction: batches of pipelines -> per-pipeline JSON (+ PCF) under OUT.

usage: ex_piping.py jobs [--batch 60]            -> writes WORK/jobs/piping.json (list of batches)
       ex_piping.py run  [--workers 8] [--limit N] [--only PLOID ...]
"""
import os, sys, re, json, time, math, argparse, collections, traceback
import numpy as np
from common import *
from sql_piping import batch_sql
import pipemap
from pipemap import Meta, bore_mm, area_of, pcf_type, skey_for

JOBF = os.path.join(WORK, 'jobs', 'piping.json')
DONE = os.path.join(WORK, 'done', 'piping')
M = None      # Meta, loaded before fork


def fetch(conn, pls):
    sets = query_sets(conn, batch_sql(guid_list(pls)))
    out = collections.defaultdict(list)
    for cols, rows in sets:
        if not rows or cols[0] != 'rs':
            if cols and cols[0] == 'rs':
                continue
            continue
        name = rows[0][0]
        c = cols[1:]
        out[name] = [dict(zip(c, r[1:])) for r in rows]
    return out


def U(x):
    return x.upper() if isinstance(x, str) else x


def xyz(a, b, c, nd=5):
    if a is None or b is None or c is None:
        return None
    return [round(float(a), nd), round(float(b), nd), round(float(c), nd)]


def dist(p, q):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q)))


def trailing_int(s):
    m = re.search(r'(\d+)$', s or '')
    return int(m.group(1)) if m else None


def mat16(r):
    try:
        return [fnum(r[k], 7) for k in ('m0', 'm1', 'm2', 'm4', 'm5', 'm6', 'm8', 'm9', 'm10', 'm12', 'm13', 'm14')]
    except KeyError:
        return None


def dir_word(v, tol_deg=10.0):
    """unit vector -> PCF direction word (X=EAST, Y=NORTH, Z=UP) if within tol of an axis."""
    if v is None:
        return None
    n = math.sqrt(sum(a * a for a in v))
    if n < 1e-9:
        return None
    v = [a / n for a in v]
    words = [((1, 0, 0), 'EAST'), ((-1, 0, 0), 'WEST'), ((0, 1, 0), 'NORTH'), ((0, -1, 0), 'SOUTH'), ((0, 0, 1), 'UP'), ((0, 0, -1), 'DOWN')]
    best = max(words, key=lambda w: sum(a * b for a, b in zip(v, w[0])))
    if sum(a * b for a, b in zip(v, best[0])) >= math.cos(math.radians(tol_deg)):
        return best[1]
    return None


# expected PCF geometry points per type: (end points, needs centre, needs branch)
EXPECT = {'PIPE': (2, 0, 0), 'PIPE-FIXED': (2, 0, 0), 'ELBOW': (2, 1, 0), 'BEND': (2, 1, 0), 'TEE': (2, 1, 1), 'OLET': (0, 1, 1),
          'REDUCER-CONCENTRIC': (2, 0, 0), 'REDUCER-ECCENTRIC': (2, 0, 0), 'FLANGE': (2, 0, 0), 'FLANGE-BLIND': (1, 0, 0),
          'VALVE': (2, 0, 0), 'INSTRUMENT': (2, 0, 0), 'CAP': (1, 0, 0), 'COUPLING': (2, 0, 0), 'UNION': (2, 0, 0),
          'FILTER': (2, 0, 0), 'MISC-COMPONENT': (1, 0, 0)}


def _dim(C, *names):
    for src in (C.get('occ_attrs') or {}, C.get('catalog_attrs') or {}):
        for n in names:
            v = src.get(n)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    return None


def estimate_open_ports(C):
    M = C['matrix']
    X, Y, O = np.array(M[0:3]), np.array(M[3:6]), np.array(M[9:12])
    known = {q['index']: np.array(q['xyz']) for q in C['ports'] if q['xyz']}
    t = C['pcf_type']
    ff = _dim(C, 'IJFaceToFace.FacetoFace')
    fc = _dim(C, 'IJFaceToCenter.FacetoCenter', 'IJFaceToCenter.Face1toCenter')
    for q in C['ports']:
        if q['xyz']:
            continue
        i, est = q['index'], None
        other = known.get(3 - i) if i in (1, 2) else None
        if t in ('VALVE', 'REDUCER-CONCENTRIC', 'REDUCER-ECCENTRIC', 'INSTRUMENT', 'FILTER', 'UNION', 'COUPLING', 'MISC-COMPONENT', 'PIPE-FIXED') and i in (1, 2):
            if other is not None and np.linalg.norm(other - O) > 1e-4:
                est = 2 * O - other
            elif ff:
                est = O + X * (ff / 2 if i == 2 else -ff / 2)
        elif t == 'TEE':
            if i in (1, 2) and other is not None:
                est = 2 * O - other
            elif i in (1, 2) and fc:
                est = O + X * (fc if i == 2 else -fc)
            elif i == 3:
                b = _dim(C, 'IJFaceToCenter.Face3toCenter', 'IJFaceToCenter.Face2toCenter', 'IJFaceToCenter.FacetoCenter')
                if b is None and known:
                    b = float(np.linalg.norm(next(iter(known.values())) - O))
                if b:
                    est = O + Y * b
        elif t in ('ELBOW', 'BEND'):
            ang = math.radians((C.get('bend') or {}).get('angle_deg') or math.degrees(_dim(C, 'IJUABendAngle.BendAngle') or math.pi / 2))
            T = float(np.linalg.norm(other - O)) if other is not None else fc
            if T:
                est = O - X * T if i == 1 else O + (math.cos(ang) * X + math.sin(ang) * Y) * T
        elif t in ('FLANGE', 'FLANGE-BLIND', 'CAP'):
            if i == 1:
                est = O
            elif i == 2:
                L = ff or ((C['ports'][0].get('flange') or {}).get('thk') or 0) * 2.5 or None
                if L:
                    est = O + X * L
        elif t == 'OLET':
            if i == 1:
                est = O
            elif i == 2:
                L = _dim(C, 'IJOlet.FacetoHeaderSurface', 'IJUAFacetoFittingCrotch.FacetoFittingCrotch', 'IJFaceToFace.FacetoFace')
                if L:
                    est = O + Y * L
        if est is not None:
            q['xyz'] = [round(float(v), 5) for v in est]
            q['xyz_source'] = 'estimated from symbol placement'
    C['ep1'] = next((q['xyz'] for q in C['ports'] if q['index'] == 1), None)
    C['ep2'] = next((q['xyz'] for q in C['ports'] if q['index'] == 2), None)
    C['ep3'] = next((q['xyz'] for q in C['ports'] if q['index'] == 3), None)


def assemble(pl, info, data):
    """pl oid + pipeline row + batch data (already filtered to this pipeline) -> JSON dict"""
    Mt = M
    runs = [r for r in data['runs']]
    run_ids = {U(r['run']) for r in runs}
    parts = [p for p in data['parts'] if U(p['run']) in run_ids]
    part_ids = {U(p['part']) for p in parts}
    ports_by_part = collections.defaultdict(list)
    for r in data['ports']:
        if U(r['part']) in part_ids:
            ports_by_part[U(r['part'])].append(r)
    conns = data['_conns']
    feats = collections.defaultdict(list)
    for f in data['feats']:
        if U(f['part']) in part_ids:
            feats[U(f['part'])].append(f)
    syms = data['_syms']
    occattr = data['_occattr']

    path = Mt.system_path(pl)
    J = collections.OrderedDict()
    J['schema'] = 's3d-pipeline/1'
    J['source'] = {'model': 'MLNG@1_MDB', 'oid': pl, 'class': 'SHPCONPipelineSystem'}
    J['name'] = (info.get('strName') or '').strip()
    J['line_number'] = J['name']
    J['description'] = info.get('Description')
    J['sequence_number'] = info.get('SequenceNumber')
    J['fluid_code'] = Mt.cl('FluidCode', info.get('FluidCode')) if info.get('FluidCode') else None
    J['fluid_system'] = Mt.cl('FluidSystem', info.get('FluidSystem')) if info.get('FluidSystem') else None
    J['system_path'] = path
    J['area'] = area_of(path)
    J['units'] = {'length': 'm', 'coordinates': 'm, global S3D frame (X east, Y north, Z up)', 'angle': 'deg', 'bore': 'mm (DN)'}
    J['attributes'] = data['_plattr'].get(U(pl), {})

    # ---- runs
    run_out = {}
    for r in runs:
        mon, _ = Mt.resolve(r.get('specproxy'))
        run_out[U(r['run'])] = collections.OrderedDict(
            oid=U(r['run']), name=(r.get('strName') or '').strip(), npd=fnum(r.get('NomDiaSize'), 4), npd_unit=r.get('NPDUnitType'),
            bore_mm=bore_mm(r.get('NomDiaSize'), r.get('NPDUnitType')), spec=mon,
            insulated=bool(r.get('IsInsulated')), insulation_thickness=fnum(r.get('InsulationThickness')),
            insulation_purpose=Mt.cl('InsulationPurpose', r.get('InsulationPurpose')),
            insulation_material=Mt.cl('InsulationMaterial', r.get('InsulationMaterial')),
            insulation_temperature=fnum(r.get('InsulationTemperature')),
            flow_direction=r.get('FlowDirection'), run_type=r.get('PipeRunType'), min_slope=fnum(r.get('MinSlope')))
    J['specs'] = sorted({v['spec'] for v in run_out.values() if v['spec']})

    # ---- components
    comps = {}
    for p in parts:
        oid = U(p['part']); cls = p['cls']
        mon, cat = Mt.resolve(p.get('madefrom'))
        cp = Mt.catparts.get(cat) if cat else None
        _, mcat = Mt.resolve(p.get('matctl'))
        mc = Mt.matctl.get(mcat) if mcat else None
        cports = {pp['PortIndex']: pp for pp in Mt.catports.get(cat, [])} if cat else {}
        part_class = cp.get('PartClass') if cp else None
        ct = Mt.cl('PipingCommodityType', cp.get('CommodityType')) if cp else None
        cc = Mt.cl('PipingCommodityClass', cp.get('CommodityClass')) if cp else None
        # ports
        pr = {}
        for r in ports_by_part.get(oid, []):
            idx = r.get('PortIndex') if r.get('PortIndex') is not None else trailing_int(r.get('pname'))
            if idx is None:
                continue
            prev = pr.get(idx)
            if prev is not None and prev.get('conn') and not r.get('conn'):
                continue
            pr[idx] = r
        ports = []
        for idx in sorted(pr):
            r = pr[idx]
            c = conns.get(U(r['conn'])) if r.get('conn') else None
            pt = xyz(r.get('PlacePointX'), r.get('PlacePointY'), r.get('PlacePointZ')) or (c['xyz'] if c else None)
            cpp = cports.get(idx, {})
            npd = r.get('NPD') if r.get('NPD') is not None else cpp.get('Npd')
            unit = r.get('NPDUnitType') or cpp.get('NpdUnitType')
            ep = r.get('EndPreparation') if r.get('EndPreparation') is not None else cpp.get('EndPrep')
            rating = r.get('PressureRating') if r.get('PressureRating') is not None else cpp.get('PressureRating')
            sched = r.get('ScheduleThickness') if r.get('ScheduleThickness') is not None else cpp.get('ScheduleThickness')
            od = fnum(r.get('PipingOutsideDiameter'))
            if not od and cp:
                if npd is not None and cp.get('PrimarySize') is not None and abs(float(npd) - float(cp['PrimarySize'])) < 1e-6:
                    od = fnum(cp.get('FirstSizeOutsideDiameter'))
                elif npd is not None and cp.get('SecondarySize') is not None and abs(float(npd) - float(cp['SecondarySize'])) < 1e-6:
                    od = fnum(cp.get('SecondSizeOutsideDiameter'))
            if not od:
                od = fnum(Mt.od(npd, unit))
            po = collections.OrderedDict(index=idx, xyz=pt, conn=U(r.get('conn')), npd=fnum(npd, 4), npd_unit=unit,
                                         bore_mm=bore_mm(npd, unit), od=od, wall=fnum(r.get('WallThicknessOrGrooveSetback')),
                                         end_prep=Mt.cl('EndPreparation', ep), end_prep_id=ep, rating=Mt.cl('PressureRating', rating),
                                         rating_id=rating, schedule=Mt.cl('ScheduleThickness', sched), end_standard=r.get('EndStandard') or cpp.get('EndStandard'),
                                         termination_class=cpp.get('TerminationClass'))
            if r.get('OrientationX') is not None:
                po['dir'] = xyz(r['OrientationX'], r['OrientationY'], r['OrientationZ'], 6)
            sfx = Mt.endsfx.get(int(ep)) if ep is not None else None
            po['end_skey'] = sfx
            if sfx == 'FL' and unit and npd is not None:
                t = Mt.flange_dims(npd, unit, ep, rating, po['end_standard'])
                if t and t.get('FlangeOutsideDiameter'):
                    po['flange'] = {'od': fnum(t['FlangeOutsideDiameter']), 'thk': fnum(t.get('FlangeThickness')),
                                    'rf_dia': fnum(t.get('RaisedFaceDiameter')), 'bolt_circle': fnum(t.get('BoltCircleDiameter')),
                                    'n_bolts': t.get('QuantityOfBoltsRequired'), 'bolt_dia': fnum(t.get('BoltDiameter')),
                                    'body_od': fnum(t.get('BodyOutsideDiameter'))}
            elif sfx in ('SW', 'SC', 'TH', 'CP') and unit and npd is not None:
                t = Mt.hub_dims(npd, unit, ep, rating)
                if t and t.get('HubOutsideDiameter'):
                    po['hub'] = {'od': fnum(t['HubOutsideDiameter']), 'thk': fnum(t.get('HubThickness')),
                                 'socket_depth': fnum(t.get('SocketDepth')), 'body_od': fnum(t.get('BodyOutsideDiameter'))}
            ports.append(po)
        # feature
        fl = feats.get(oid, [])
        f = None
        if fl:
            f = sorted(fl, key=lambda x: (0 if x.get('BendAngle') is not None else (1 if x.get('featcls') == 80035 else 2)))[0]
        ep1 = ports[0]['end_prep_id'] if ports else None
        cpe1 = (cports.get(1) or {}).get('EndPrep')
        sk, pcf_map, sk_src = skey_for(Mt, part_class, None, cpe1 if cpe1 is not None else ep1)
        ptype = pcf_type(cls, part_class, ct, cc, pcf_map, len(ports))
        if sk is None and cls != 80012:
            sk, _, sk_src = skey_for(Mt, None, ptype, cpe1 if cpe1 is not None else ep1)
        C = collections.OrderedDict()
        C['oid'] = oid
        C['name'] = (p.get('strName') or '').strip()
        C['run'] = U(p['run'])
        C['occ_class'] = {80012: 'ROUTEPipeOccur', 80005: 'ROUTEPipeComponentOcc', 80054: 'ROUTEPipeInstrumentOcc', 80055: 'ROUTEPipeSpecialtyOcc'}.get(cls, str(cls))
        C['pcf_type'] = ptype
        C['skey'] = sk
        C['skey_source'] = sk_src
        C['commodity_type'] = ct
        C['commodity_class'] = cc
        C['commodity_subclass'] = Mt.cl('PipingCommoditySubClass', cp.get('CommoditySubClass')) if cp else None
        C['part_class'] = part_class
        C['catalog_part'] = mon
        C['item_code'] = (mc or {}).get('ContractorCommodityCode') or (cp or {}).get('TagCommodityCode') or (cp or {}).get('IndustryCommodityCode')
        C['industry_commodity_code'] = (cp or {}).get('IndustryCommodityCode')
        C['part_number'] = (cp or {}).get('PartNumber')
        C['tag'] = (cp or {}).get('TagNumber') or (C['name'] if cls in (80054, 80055) else None)
        C['description'] = (mc or {}).get('ShortMaterialDescription') or (cp or {}).get('TagDescription') or p.get('descr') or (cp or {}).get('PartDescription')
        C['material'] = Mt.cl('MaterialsGrade', (cp or {}).get('MaterialGrade'))
        C['geometry_type'] = Mt.cl('GeometryType', (cp or {}).get('GeometryType'))
        C['size1'] = fnum((cp or {}).get('PrimarySize'), 4)
        C['size2'] = fnum((cp or {}).get('SecondarySize'), 4)
        C['size_unit'] = (cp or {}).get('PriSizeNPDUnits')
        C['schedule1'] = Mt.cl('ScheduleThickness', (cp or {}).get('FirstSizeSchedule'))
        C['schedule2'] = Mt.cl('ScheduleThickness', (cp or {}).get('SecondSizeSchedule'))
        C['od1'] = fnum((cp or {}).get('FirstSizeOutsideDiameter'))
        C['od2'] = fnum((cp or {}).get('SecondSizeOutsideDiameter'))
        C['ports'] = ports
        C['ep1'] = next((q['xyz'] for q in ports if q['index'] == 1), None)
        C['ep2'] = next((q['xyz'] for q in ports if q['index'] == 2), None)
        C['ep3'] = next((q['xyz'] for q in ports if q['index'] == 3), None)
        C['cp'] = xyz(f['CPX'], f['CPY'], f['CPZ']) if f else None
        C['feature_class'] = {80036: 'Turn', 80035: 'Branch', 80037: 'Straight', 80034: 'AlongLeg', 80033: 'End', 80073: 'Curve'}.get(f['featcls'], f['featcls']) if f else None
        if f and f.get('BendAngle') is not None:
            C['bend'] = {'radius': fnum(f.get('BendRadius')), 'angle_deg': fnum(math.degrees(f['BendAngle']), 4),
                         'turn_type': f.get('TurnType'), 'miters': f.get('NoOfMiters')}
        if f and f.get('featcls') == 80035 and f.get('BranchAngle') is not None:
            C['branch_angle_deg'] = fnum(math.degrees(f['BranchAngle']), 4)
        if f and f.get('Tag'):
            C['feature_tag'] = f['Tag']
        if cls == 80012:
            C['length'] = fnum(p.get('PipeLength'))
            C['cut_length'] = fnum(p.get('CutLength'))
            C['plain_piping'] = p.get('bIsPlainPiping')
        C['weight'] = fnum(p.get('wt'), 3)
        C['insulated'] = bool(p.get('ins')) if p.get('ins') is not None else None
        C['short_code'] = p.get('ShortCode')
        C['option_code'] = p.get('OptionCode')
        C['matrix'] = syms.get(oid)
        if cat and cat in Mt.catattrs:
            C['catalog_attrs'] = Mt.catattrs[cat]
        if oid in occattr:
            C['occ_attrs'] = occattr[oid]
        if mc:
            C['valve_operator'] = mc.get('ValveOperatorPartNumber') or None
            C['fabrication_category'] = Mt.cl('FabricationCategory', mc.get('FabricationCategory'))
        C['bore1_mm'] = ports[0]['bore_mm'] if ports else bore_mm(C['size1'], C['size_unit'])
        C['bore2_mm'] = (ports[1]['bore_mm'] if len(ports) > 1 else None) or bore_mm(C['size2'], C['size_unit'])
        comps[oid] = C

    # ---- ports without size data (model-resident instruments/specialties): neighbour port at the same
    #      connection, else the occurrence's IJDynamicPipePortN attributes
    port_at_conn = collections.defaultdict(list)
    for C in comps.values():
        for q in C['ports']:
            if q['conn']:
                port_at_conn[q['conn']].append((C['oid'], q))
    for C in comps.values():
        oa = C.get('occ_attrs') or {}
        for q in C['ports']:
            if q['bore_mm'] is None or q['od'] is None or q['end_prep'] is None:
                src = None
                for o2, q2 in port_at_conn.get(q['conn'], []) if q['conn'] else []:
                    if o2 != C['oid'] and q2['bore_mm']:
                        src = q2; break
                n = q['index']
                if q['bore_mm'] is None:
                    if src:
                        q['bore_mm'], q['npd'], q['npd_unit'] = src['bore_mm'], src['npd'], src['npd_unit']
                        q['size_source'] = 'neighbour port'
                    elif oa.get('IJDynamicPipePort%d.Npd%d' % (n, n)):
                        v = oa['IJDynamicPipePort%d.Npd%d' % (n, n)]
                        u = oa.get('IJDynamicPipePort%d.NpdUnitType%d' % (n, n)) or ('mm' if float(v) > 8 else 'in')
                        q['npd'], q['npd_unit'], q['bore_mm'] = fnum(v, 4), u, bore_mm(v, u)
                        q['size_source'] = 'occurrence attribute'
                if q['od'] is None:
                    q['od'] = (src or {}).get('od') or fnum(Mt.od(q['npd'], q['npd_unit']))
                if q['end_prep'] is None:
                    ep = oa.get('IJDynamicPipePort%d.EndPreparation%d' % (n, n))
                    if isinstance(ep, str):
                        q['end_prep'] = ep
                    elif src and src.get('end_prep') and src.get('end_skey') == 'FL':
                        q['end_prep'] = src['end_prep']; q['end_skey'] = 'FL'
                        if src.get('flange'):
                            q['flange'] = src['flange']
                if q.get('rating') is None:
                    r = oa.get('IJDynamicPipePort%d.PressureRating%d' % (n, n))
                    q['rating'] = r if isinstance(r, str) else (src or {}).get('rating')
        if C['ports']:
            C['bore1_mm'] = C['ports'][0]['bore_mm'] or C['bore1_mm']
            if len(C['ports']) > 1:
                C['bore2_mm'] = C['ports'][1]['bore_mm'] or C['bore2_mm']

    # ---- open (unconnected) fitting ports: estimate from the CORESymbol placement using the verified symbol
    #      conventions (port1 -X, port2 +X, tee branch / olet outlet +Y, elbow outlet cos(a)X+sin(a)Y,
    #      body origin mid-way for valves/reducers/instruments, at the face for flanges/caps/olets)
    for C in comps.values():
        if C['pcf_type'] == 'PIPE' or not C.get('matrix') or all(q['xyz'] for q in C['ports']):
            continue
        estimate_open_ports(C)

    # ---- olet centre point: project header surface point onto header centre line
    ext_pipes = data['_extpipes']
    for C in comps.values():
        if C['pcf_type'] != 'OLET' or not C['ep1'] or not C['ep2']:
            continue
        hp = None
        p1 = next((q for q in C['ports'] if q['index'] == 1), None)
        if p1 and p1['conn']:
            for other in conns.get(p1['conn'], {}).get('parts', []):
                if other == C['oid']:
                    continue
                if other in comps and comps[other]['pcf_type'] == 'PIPE' and comps[other]['ep1'] and comps[other]['ep2']:
                    hp = (comps[other]['ep1'], comps[other]['ep2'], comps[other]['ports'][0].get('od')); break
                if other in ext_pipes:
                    hp = ext_pipes[other]; break
        if hp:
            a, b = np.array(hp[0]), np.array(hp[1]); d = b - a; L = np.linalg.norm(d)
            if L > 1e-9:
                d /= L
                s = np.array(C['ep1'])
                t = float(np.dot(s - a, d))
                C['header_point'] = [round(float(v), 5) for v in (a + d * t)]
                C['cp_source'] = 'header centreline projection'
        if 'header_point' not in C:
            n = np.array(C['ep2']) - np.array(C['ep1']); L = np.linalg.norm(n)
            hod = C.get('od1') if (C.get('od1') or 0) > (C['ports'][-1].get('od') or 0) else None
            if L > 1e-9 and hod:
                C['header_point'] = [round(float(v), 5) for v in (np.array(C['ep1']) - n / L * hod / 2)]
                C['cp_source'] = 'surface point - header OD/2 along branch axis'

    # ---- ordering inside each run (DFS along connections, port 2 before 3)
    adj = collections.defaultdict(list)
    for C in comps.values():
        for q in C['ports']:
            if not q['conn']:
                continue
            for other in conns.get(q['conn'], {}).get('parts', []):
                if other != C['oid'] and other in comps and comps[other]['run'] == C['run']:
                    adj[C['oid']].append((q['index'], other))
    order = []
    by_run = collections.defaultdict(list)
    for C in comps.values():
        by_run[C['run']].append(C['oid'])
    for run in sorted(by_run, key=lambda r: run_out.get(r, {}).get('name', '')):
        members = sorted(by_run[run])
        seen = set()
        starts = sorted(members, key=lambda o: (len({x for _, x in adj.get(o, [])}) > 1, o))
        seq = 0
        for s in starts:
            if s in seen:
                continue
            stack = [s]
            while stack:
                o = stack.pop()
                if o in seen:
                    continue
                seen.add(o)
                comps[o]['seq'] = seq; seq += 1
                order.append(o)
                nxt = sorted({(i, x) for i, x in adj.get(o, []) if x not in seen}, reverse=True)
                for _, x in nxt:
                    stack.append(x)
    J['runs'] = [run_out[r] for r in sorted(run_out, key=lambda r: run_out[r]['name'])]
    J['components'] = [comps[o] for o in order]

    # ---- connections touching this pipeline
    cons = []
    touched = set()
    for C in comps.values():
        for q in C['ports']:
            if q['conn']:
                touched.add(q['conn'])
    for co in sorted(touched | {k for k, v in conns.items() if v.get('ownerrun') in run_out}):
        c = conns.get(co)
        if not c:
            continue
        e = collections.OrderedDict(oid=co, xyz=c['xyz'], type=c['type'], size=c['size'], owned=c.get('ownerrun') in run_out,
                                    parts=[x for x in c['parts'] if x in comps], items=c['items'] if c.get('ownerrun') in run_out else [])
        ext = []
        for x in c['parts']:
            if x not in comps:
                ext.append({'kind': 'PIPELINE', 'part': x, 'pipeline': c['part_pl'].get(x, (None, None))[1], 'pipeline_oid': c['part_pl'].get(x, (None, None))[0]})
        for eq in c.get('equip', []):
            ext.append({'kind': 'EQUIPMENT', 'equipment': eq[1], 'equipment_oid': eq[0], 'nozzle': eq[2]})
        if ext:
            e['external'] = ext
        cons.append(e)
    J['connections'] = cons

    # ---- supports
    sups = []
    for s in data['supports']:
        if U(s['pl']) != pl:
            continue
        so = U(s['support'])
        org = xyz(s.get('o0'), s.get('o1'), s.get('o2'))
        near = None
        if org:
            best = 1e9
            for C in comps.values():
                if C['pcf_type'] != 'PIPE' or not C['ep1'] or not C['ep2']:
                    continue
                a, b, pnt = np.array(C['ep1']), np.array(C['ep2']), np.array(org)
                d = b - a; L2 = float(d @ d)
                t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, float((pnt - a) @ d) / L2))
                dd = float(np.linalg.norm(a + d * t - pnt))
                if dd < best:
                    best, near = dd, C
        sc = data['_supcomps'].get(so, [])
        comps_out = []
        for x in sc:
            mon, _ = Mt.resolve(x.get('madefrom'))
            comps_out.append(collections.OrderedDict(
                oid=U(x['comp']), cls=x.get('ClassId'), role=x.get('role'), bom=x.get('BOM'), catalog_part=mon,
                bbox=[fnum(x.get(k), 4) for k in ('xmin', 'ymin', 'zmin', 'xmax', 'ymax', 'zmax')] if x.get('xmin') is not None else None,
                matrix=mat16(x) if x.get('m0') is not None else None))
        sups.append(collections.OrderedDict(
            oid=so, name=(s.get('strName') or '').strip(), bom=s.get('BOMdescription'), catalog_assembly=s.get('CatalogAssembly'),
            status=s.get('SupportStatus'), max_load=fnum(s.get('MaxLoad')), xyz=org,
            z_axis=xyz(s.get('z0'), s.get('z1'), s.get('z2'), 6), x_axis=xyz(s.get('x0'), s.get('x1'), s.get('x2'), 6),
            bbox=[fnum(s.get(k), 4) for k in ('xmin', 'ymin', 'zmin', 'xmax', 'ymax', 'zmax')] if s.get('xmin') is not None else None,
            supported_part=near['oid'] if near else None, bore_mm=near['bore1_mm'] if near else None,
            components=comps_out))
    J['supports'] = sups

    # ---- checks
    J['checks'] = checks(J, comps, conns)
    pts = [q['xyz'] for C in comps.values() for q in C['ports'] if q['xyz']]
    if pts:
        a = np.array(pts)
        J['bbox'] = [round(float(v), 4) for v in list(a.min(0)) + list(a.max(0))]
    J['counts'] = dict(collections.Counter(C['pcf_type'] for C in comps.values()))
    J['counts']['_components'] = len(comps)
    J['counts']['_connections'] = len(cons)
    J['counts']['_supports'] = len(sups)
    J['counts']['_welds'] = sum(1 for e in cons for i in e['items'] if i['kind'] == 'WELD')
    J['counts']['_gaskets'] = sum(1 for e in cons for i in e['items'] if i['kind'] == 'GASKET')
    J['counts']['_boltsets'] = sum(1 for e in cons for i in e['items'] if i['kind'] == 'BOLT')
    return J


SETBACK_MAX = 0.012


def checks(J, comps, conns, tol=0.001):
    ck = collections.OrderedDict()
    bad_pts = []
    for C in comps.values():
        ne, nc, nb = EXPECT.get(C['pcf_type'], (1, 0, 0))
        ne = min(ne, max(1, len([q for q in C['ports'] if q['index'] in (1, 2)])))
        have = sum(1 for k in ('ep1', 'ep2') if C.get(k))
        ok = have >= ne and (not nc or C.get('cp') or C.get('header_point')) and (not nb or C.get('ep3') or C.get('ep2'))
        if C['pcf_type'] == 'OLET':
            ok = bool(C.get('ep1') and C.get('ep2'))
        if not ok:
            bad_pts.append({'oid': C['oid'], 'type': C['pcf_type'], 'have_ep': have, 'need_ep': ne})
    ck['components'] = len(comps)
    ck['point_count_fail'] = len(bad_pts)
    ck['point_count_fail_samples'] = bad_pts[:10]
    # connectivity: at every connection joining two parts of this pipeline, the ports must coincide
    gaps, nconn, bore_mis, setbacks, stubs = [], 0, [], [], 0
    for co, c in conns.items():
        ps = [x for x in c['parts'] if x in comps]
        if len(ps) < 2:
            continue
        pp = []
        for x in ps:
            q = next((q for q in comps[x]['ports'] if q['conn'] == co), None)
            if q and q['xyz']:
                pp.append((x, q))
        if len(pp) < 2:
            continue
        nconn += 1
        g = max(dist(pp[0][1]['xyz'], y[1]['xyz']) for y in pp[1:])
        if g > SETBACK_MAX:
            gaps.append({'conn': co, 'gap_m': round(g, 5), 'parts': [x for x, _ in pp]})
        elif g > tol:
            setbacks.append(g)
        b = {q['bore_mm'] for _, q in pp if q['bore_mm']}
        if any(comps[x]['pcf_type'] == 'PIPE' and q['index'] >= 3 for x, q in pp):
            stubs += 1
        elif len(b) > 1:
            bore_mis.append({'conn': co, 'bores': sorted(b), 'types': [comps[x]['pcf_type'] for x, _ in pp]})
    ck['internal_connections'] = nconn
    ck['connection_setback'] = len(setbacks)      # slip-on / socket insertion or gasket gap, <= 12 mm (expected)
    ck['connection_setback_max_m'] = round(max(setbacks, default=0.0), 5)
    ck['connection_gap_fail'] = len(gaps)
    ck['connection_gap_max_m'] = max((g['gap_m'] for g in gaps), default=0.0)
    ck['connection_gap_samples'] = sorted(gaps, key=lambda g: -g['gap_m'])[:10]
    ck['stub_in_branches'] = stubs
    ck['bore_mismatch'] = len(bore_mis)
    ck['bore_mismatch_samples'] = bore_mis[:10]
    # sequential continuity within each run (consecutive components share a point)
    seqbreak, npairs = 0, 0
    last = {}
    for C in J['components']:
        r = C['run']
        if r in last:
            npairs += 1
            A = [q['xyz'] for q in last[r]['ports'] if q['xyz']]
            B = [q['xyz'] for q in C['ports'] if q['xyz']]
            if A and B and min(dist(a, b) for a in A for b in B) > tol:
                seqbreak += 1
        last[r] = C
    ck['sequence_pairs'] = npairs
    ck['sequence_breaks'] = seqbreak       # a break = a new branch/segment start in DFS order, not an error by itself
    # pipe length vs port distance
    lenerr = 0
    for C in comps.values():
        if C['pcf_type'] == 'PIPE' and C.get('length') and C['ep1'] and C['ep2']:
            if abs(dist(C['ep1'], C['ep2']) - C['length']) > tol:
                lenerr += 1
    ck['pipe_length_mismatch'] = lenerr
    ck['open_ports'] = sum(1 for C in comps.values() for q in C['ports'] if not q['xyz'])
    ck['open_ports_estimated'] = sum(1 for C in comps.values() for q in C['ports'] if q.get('xyz_source'))
    ck['unresolved_catalog'] = sum(1 for C in comps.values() if not C['catalog_part'] and C['occ_class'] == 'ROUTEPipeComponentOcc')
    return ck


def prep_batch(data):
    """index shared batch data"""
    conns = {}
    for c in data['conns']:
        conns[U(c['conn'])] = {'xyz': xyz(c['LocationX'], c['LocationY'], c['LocationZ']), 'type': M.cl('ConnectionType', c.get('ConnectionType')),
                               'size': fnum(c.get('ConnectionSize')), 'ownerrun': U(c.get('ownerrun')), 'parts': [], 'items': [],
                               'equip': [], 'part_pl': {}}
    for r in data['connparts']:
        c = conns.get(U(r['conn']))
        if c is None:
            continue
        x = U(r['part'])
        if x not in c['parts']:
            c['parts'].append(x)
        if r.get('otherpl'):
            c['part_pl'][x] = (U(r['otherpl']), (r.get('otherplname') or '').strip())
    for r in data['connports']:
        c = conns.get(U(r['conn']))
        if c is not None and r.get('equip'):
            c['equip'].append((U(r['equip']), (r.get('equipname') or '').strip(), r.get('nozzle')))
    for r in data['items']:
        c = conns.get(U(r['conn']))
        if c is None:
            continue
        k = {80039: 'WELD', 80040: 'GASKET', 80041: 'BOLT'}.get(r.get('ClassId'))
        if k is None:
            k = 'WELD' if r.get('WeldType') is not None else ('GASKET' if r.get('GasketSizedCommodityCode') else ('BOLT' if r.get('BoltQuantity') else str(r.get('ClassId'))))
        it = collections.OrderedDict(kind=k, oid=U(r['item']), name=r.get('strName'))
        if k == 'WELD':
            it.update(weld_type=M.cl('WeldType', r.get('WeldType')), weld_class=r.get('WeldClass'), xyz=xyz(r.get('wx'), r.get('wy'), r.get('wz')),
                      thickness=fnum(r.get('WeldThickness')), gap=fnum(r.get('WeldGap')), wps=r.get('WPSNumber'))
        elif k == 'GASKET':
            it.update(item_code=r.get('GasketSizedCommodityCode'), description=r.get('ItemDescription'))
        elif k == 'BOLT':
            it.update(quantity=r.get('BoltQuantity'), dia=fnum(r.get('BoltDia')), length=fnum(r.get('BoltLength')),
                      calc_length=fnum(r.get('BoltCalcLength')), nuts=r.get('NutQuantity'), washers=r.get('WasherQuantity'),
                      nut_code=r.get('NutSizedCommodityCode'), description=r.get('ItemDescription'))
        c['items'].append(it)
    data['_conns'] = conns
    sc = collections.defaultdict(list)
    for x in data['supcomps']:
        sc[U(x['support'])].append(x)
    data['_supcomps'] = sc
    data['_syms'] = {U(r['part']): mat16(r) for r in data['syms']}
    occ = collections.defaultdict(list)
    for r in data['occattr']:
        occ[U(r['part'])].append((r['iid'], r['dispid'], r['d'], r['l'], r['s']))
    data['_occattr'] = {k: M.named_attrs(v) for k, v in occ.items()}
    pa = collections.defaultdict(list)
    for r in data['plattr']:
        pa[U(r['oid'])].append((r['iid'], r['dispid'], r['d'], r['l'], r['s']))
    data['_plattr'] = {k: M.named_attrs(v) for k, v in pa.items()}
    ext = {}
    for r in data.get('extpipes', []):
        ext.setdefault(U(r['part']), []).append(xyz(r['X'], r['Y'], r['Z']))
    data['_extpipes'] = {k: (v[0], v[1], None) for k, v in ext.items() if len(v) >= 2}
    return data


def out_name(J):
    return '%s__%s' % (safe_name(J['name'], 100), J['source']['oid'].replace('-', '')[16:])


def process_batch(bid, pls, conn, infos, write=True):
    t0 = time.time()
    data = fetch(conn, pls)
    t1 = time.time()
    prep_batch(data)
    res = []
    import pcfgen
    for pl in pls:
        pl = pl.upper()
        try:
            sub = dict(data)
            sub['runs'] = [r for r in data['runs'] if U(r['pl']) == pl]
            J = assemble(pl, infos.get(pl, {}), sub)
            nm = out_name(J)
            J['files'] = {'json': 'json/pipelines/%s.json.gz' % nm, 'pcf': 'pcf/%s/%s.pcf' % (safe_name(J['area'].replace('/', '__'), 80), nm)}
            pcf_txt, pstat = pcfgen.to_pcf(J)
            J['checks']['pcf'] = pstat
            if write:
                write_json(os.path.join(OUT, J['files']['json']), J)
                pp = os.path.join(OUT, J['files']['pcf'])
                os.makedirs(os.path.dirname(pp), exist_ok=True)
                with open(pp + '.tmp', 'w') as f:
                    f.write(pcf_txt)
                os.replace(pp + '.tmp', pp)
            res.append({'pl': pl, 'name': J['name'], 'area': J['area'], 'file': nm, 'n': len(J['components']),
                        'counts': J['counts'], 'checks': {k: v for k, v in J['checks'].items() if not k.endswith('samples') and k != 'pcf'},
                        'pcf': pstat, 'bbox': J.get('bbox'), 'json': J['files']['json'], 'pcf_file': J['files']['pcf']})
        except Exception as e:
            res.append({'pl': pl, 'error': '%s: %s' % (type(e).__name__, e), 'tb': traceback.format_exc()[-1500:]})
    return res, {'sql_s': round(t1 - t0, 2), 'total_s': round(time.time() - t0, 2)}


# ---------------------------------------------------------------- job runner
def make_jobs(batch):
    pls = load_pkl('pipelines')
    pls = sorted(pls, key=lambda d: d['oid'])
    jobs = []
    for i in range(0, len(pls), batch):
        jobs.append({'id': 'pb%05d' % (i // batch), 'pls': [d['oid'].upper() for d in pls[i:i + batch]]})
    os.makedirs(os.path.dirname(JOBF), exist_ok=True)
    with open(JOBF, 'w') as f:
        json.dump(jobs, f)
    print('jobs', len(jobs), 'pipelines', len(pls))


_conn = None


def _worker(job):
    global _conn
    if _conn is None:
        _conn = connect(MDB)
    infos = _INFOS
    try:
        res, tm = process_batch(job['id'], job['pls'], _conn, infos)
        rec = {'id': job['id'], 'at': utcnow(), 'timing': tm, 'results': res}
    except Exception as e:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
        rec = {'id': job['id'], 'at': utcnow(), 'error': '%s: %s' % (type(e).__name__, e), 'tb': traceback.format_exc()[-2000:]}
        return rec
    os.makedirs(DONE, exist_ok=True)
    write_json(os.path.join(DONE, job['id'] + '.json'), rec, gz=False)
    return {'id': job['id'], 'n': len(res), 'err': sum(1 for r in res if 'error' in r), 'timing': tm}


_INFOS = {}


def run(workers, limit=None, only=None):
    global M, _INFOS
    M = Meta()
    _INFOS = {d['oid'].upper(): d for d in load_pkl('pipelines')}
    pipemap.M = M
    jobs = json.load(open(JOBF))
    if only:
        jobs = [{'id': 'only_%d' % i, 'pls': [o.upper()]} for i, o in enumerate(only)]
    else:
        jobs = [j for j in jobs if not os.path.exists(os.path.join(DONE, j['id'] + '.json'))]
    if limit:
        jobs = jobs[:limit]
    log('piping: %d jobs to run, %d workers' % (len(jobs), workers))
    import multiprocessing as mp
    t0 = time.time(); n = 0
    if workers <= 1:
        for j in jobs:
            r = _worker(j); n += 1
            log('%s %s' % (n, json.dumps(r)[:300]))
        return
    ctx = mp.get_context('fork')
    with ctx.Pool(workers, maxtasksperchild=200) as pool:
        for r in pool.imap_unordered(_worker, jobs):
            n += 1
            if n % 10 == 0 or 'error' in r:
                log('%d/%d %.0fs %s' % (n, len(jobs), time.time() - t0, json.dumps(r)[:400]))
    log('piping done %d jobs %.0fs' % (n, time.time() - t0))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd')
    ap.add_argument('--batch', type=int, default=60)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--only', nargs='*')
    a = ap.parse_args()
    if a.cmd == 'jobs':
        make_jobs(a.batch)
    elif a.cmd == 'run':
        run(a.workers, a.limit, a.only)
