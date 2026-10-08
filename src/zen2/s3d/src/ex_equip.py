"""Equipment extraction: placement, bbox, catalog class, system, nozzles, primitive shapes (+ params) per area.

ex_equip.py run    -> WORK/equip/pages/*.json.gz
ex_equip.py merge  -> OUT/json/equipment/<area>.jsonl.gz
"""
import os, sys, json, time, math, argparse, collections, gzip, glob
from common import *
from pipemap import Meta, area_of, bore_mm

PDIR = os.path.join(WORK, 'equip', 'pages')
HasEqpComponents = '9091AB37-18ED-4A1C-9FCE-A94B93606F17'

SQL = """
SET NOCOUNT ON;
SELECT e.oid INTO #eq FROM dbo.EQUIPSmartEquipment e WHERE e.oid > '%(LO)s' AND e.oid <= '%(HI)s';
CREATE CLUSTERED INDEX ix_eq ON #eq(oid);
SELECT q.oid AS eq, q.oid AS owner INTO #own FROM #eq q;
INSERT INTO #own SELECT q.oid, c.oidTarget FROM #eq q JOIN dbo.CORERelationOrigin c ON c.oid = q.oid AND c.RelationType = '%(HEC)s';
CREATE CLUSTERED INDEX ix_own ON #own(owner);

SELECT 'eq' AS rs, CAST(e.oid AS char(36)) eq, n.strName, b.persistentFlag pf, e.DryWeight, e.WetWeight, e.DryCGX, e.DryCGY, e.DryCGZ,
       e.strDescription, m.Description jdesc,
       m.x0, m.x1, m.x2, m.y0, m.y1, m.y2, m.z0, m.z1, m.z2, m.o0, m.o1, m.o2,
       si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax,
       CAST(sysr.oid AS char(36)) sysoid, pcn.RelationName CatalogPartClass
FROM #eq q JOIN dbo.EQUIPSmartEquipment e ON e.oid = q.oid
LEFT JOIN dbo.JEquipment m ON m.oid = e.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid = e.oid
LEFT JOIN dbo.CORENamedItem n ON n.oid = e.oid
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = e.oid
OUTER APPLY (SELECT TOP 1 r.oid FROM dbo.CORERelationOrigin r WHERE r.oidTarget = e.oid AND r.RelationType = '%(HasEqpAsChild)s') sysr
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin s
             JOIN dbo.CORERelationOrigin pc ON pc.oidTarget = s.oidTarget AND pc.RelationType = '%(PartClassParts)s'
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = pc.oid AND po.RelationType = '%(ProxyOwner)s'
             WHERE s.oid = e.oid AND s.RelationType = '%(SOtoSI)s') pcn;

SELECT 'comp' AS rs, CAST(o.eq AS char(36)) eq, CAST(o.owner AS char(36)) comp, n.strName
FROM #own o LEFT JOIN dbo.CORENamedItem n ON n.oid = o.owner WHERE o.owner <> o.eq;

SELECT 'noz' AS rs, CAST(o.eq AS char(36)) eq, CAST(o.owner AS char(36)) owner, CAST(z.oid AS char(36)) noz, r.RelationName label, z.strLabel,
       z.dNPD, z.strNPDUnitType, z.lEndPrep, z.lPressureRating, z.lScheduleThickness, z.lEndStandard, z.lPortIndex,
       z.gposPlacePointX X, z.gposPlacePointY Y, z.gposPlacePointZ Z, z.gvecOrientationX DX, z.gvecOrientationY DY, z.gvecOrientationZ DZ,
       z.gvecRadialOrientationX RX, z.gvecRadialOrientationY RY, z.gvecRadialOrientationZ RZ,
       z.dPipingOutsideDiameter OD, z.dFlangeOrHubOutsideDiameter FlangeOD, z.dFlangeOrHubThickness FlangeThk, z.dLength NozzleLength,
       z.dWallThicknessOrGrooveSetback Wall, z.dRaisedFaceOrSocketDiameter RFDia, z.dFlangeProjectionOrSocketOffset Proj, z.eFlowDirection,
       z.bIsInsulated, z.dInsulationThickness
FROM #own o JOIN dbo.CORERelationOrigin r ON r.oid = o.owner AND r.RelationType = '%(DistribPorts)s'
JOIN dbo.EQUIPPipeNozzle z ON z.oid = r.oidTarget;

SELECT CAST(o.eq AS char(36)) eq, CAST(o.owner AS char(36)) owner, h.oidTarget shape INTO #sh
FROM #own o JOIN dbo.CORERelationOrigin h ON h.oid = o.owner AND h.RelationType = '%(HasShapes)s';
CREATE CLUSTERED INDEX ix_sh ON #sh(shape);

SELECT 'shape' AS rs, s.eq, s.owner, CAST(s.shape AS char(36)) shape, sp.RelationName ShapeType, n.strName,
       y.ServerToClient0 m0, y.ServerToClient1 m1, y.ServerToClient2 m2, y.ServerToClient4 m4, y.ServerToClient5 m5, y.ServerToClient6 m6,
       y.ServerToClient8 m8, y.ServerToClient9 m9, y.ServerToClient10 m10, y.ServerToClient12 m12, y.ServerToClient13 m13, y.ServerToClient14 m14,
       es.dDir1X, es.dDir1Y, es.dDir1Z, es.dDir2X, es.dDir2Y, es.dDir2Z, si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax
FROM #sh s
LEFT JOIN dbo.CORESymbol y ON y.oid = s.shape
LEFT JOIN dbo.EQUIPShape es ON es.oid = s.shape
LEFT JOIN dbo.CORENamedItem n ON n.oid = s.shape
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = s.shape
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin d
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = d.oidTarget AND po.RelationType = '%(ProxyOwner)s'
             WHERE d.oid = s.shape AND d.RelationType = '%(ShapeDefinedFrom)s') sp;

SELECT 'sattr' AS rs, CAST(s.shape AS char(36)) shape, CAST(a.iid AS char(36)) iid, a.dispid, a.value
FROM #sh s JOIN dbo.COREDoubleAttribute a ON a.oid = s.shape;

SELECT 'eattr' AS rs, CAST(q.oid AS char(36)) eq, CAST(a.iid AS char(36)) iid, a.dispid, a.d, a.l, a.s
FROM #eq q CROSS APPLY (
  SELECT iid, dispid, value d, CAST(NULL AS int) l, CAST(NULL AS nvarchar(400)) s FROM dbo.COREDoubleAttribute WHERE oid = q.oid
  UNION ALL SELECT iid, dispid, NULL, value, NULL FROM dbo.CORELongAttribute WHERE oid = q.oid
  UNION ALL SELECT iid, dispid, NULL, NULL, CAST(value AS nvarchar(400)) FROM dbo.COREBstrAttribute WHERE oid = q.oid) a;
DROP TABLE #sh; DROP TABLE #own; DROP TABLE #eq;
"""


def xyz(a, b, c, nd=5):
    if a is None or b is None or c is None:
        return None
    return [round(float(a), nd), round(float(b), nd), round(float(c), nd)]


def run(npage=4000):
    M = Meta()
    c = connect(MDB)
    cols, rows = query(c, "SELECT CAST(oid AS char(36)) FROM dbo.EQUIPSmartEquipment ORDER BY oid")
    oids = [r[0] for r in rows]
    bounds = ['00000000-0000-0000-0000-000000000000'] + [oids[i] for i in range(npage - 1, len(oids), npage)] + ['FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF']
    os.makedirs(PDIR, exist_ok=True)
    tot = collections.Counter()
    for pi in range(len(bounds) - 1):
        fn = os.path.join(PDIR, 'ep%03d.json.gz' % pi)
        if os.path.exists(fn):
            continue
        t = time.time()
        sets = query_sets(c, SQL % dict(R, LO=bounds[pi], HI=bounds[pi + 1], HEC=HasEqpComponents))
        D = collections.defaultdict(list)
        for cols, rows in sets:
            if rows and cols[0] == 'rs':
                D[rows[0][0]] = [dict(zip(cols[1:], r[1:])) for r in rows]
        sattr = collections.defaultdict(list)
        for r in D['sattr']:
            sattr[r['shape'].upper()].append((r['iid'], r['dispid'], r['value'], None, None))
        eattr = collections.defaultdict(list)
        for r in D['eattr']:
            eattr[r['eq'].upper()].append((r['iid'], r['dispid'], r['d'], r['l'], r['s']))
        nozz = collections.defaultdict(list); shapes = collections.defaultdict(list); comps = collections.defaultdict(list)
        for r in D['comp']:
            comps[r['eq'].upper()].append({'oid': r['comp'].upper(), 'name': (r.get('strName') or '').strip()})
        for r in D['noz']:
            nozz[r['eq'].upper()].append(collections.OrderedDict(
                oid=r['noz'].upper(), owner=r['owner'].upper(), label=r.get('label') or r.get('strLabel'), npd=fnum(r.get('dNPD'), 4),
                npd_unit=r.get('strNPDUnitType'), bore_mm=bore_mm(r.get('dNPD'), r.get('strNPDUnitType')),
                end_prep=M.cl('EndPreparation', r.get('lEndPrep')), rating=M.cl('PressureRating', r.get('lPressureRating')),
                schedule=M.cl('ScheduleThickness', r.get('lScheduleThickness')), port_index=r.get('lPortIndex'),
                xyz=xyz(r['X'], r['Y'], r['Z']), dir=xyz(r['DX'], r['DY'], r['DZ'], 7), radial=xyz(r['RX'], r['RY'], r['RZ'], 7),
                od=fnum(r.get('OD')), flange_od=fnum(r.get('FlangeOD')), flange_thk=fnum(r.get('FlangeThk')), length=fnum(r.get('NozzleLength')),
                wall=fnum(r.get('Wall')), rf_dia=fnum(r.get('RFDia')), projection=fnum(r.get('Proj')), flow=r.get('eFlowDirection'),
                insulated=r.get('bIsInsulated'), insulation_thickness=fnum(r.get('dInsulationThickness'))))
        for r in D['shape']:
            prm = M.named_attrs(sattr.get(r['shape'].upper(), []))
            shapes[r['eq'].upper()].append(collections.OrderedDict(
                oid=r['shape'].upper(), owner=r['owner'].upper(), shape_type=r.get('ShapeType'), name=(r.get('strName') or '').strip(),
                params=prm, matrix=[fnum(r[k], 7) for k in ('m0', 'm1', 'm2', 'm4', 'm5', 'm6', 'm8', 'm9', 'm10', 'm12', 'm13', 'm14')] if r.get('m0') is not None else None,
                dir1=xyz(r.get('dDir1X'), r.get('dDir1Y'), r.get('dDir1Z'), 7), dir2=xyz(r.get('dDir2X'), r.get('dDir2Y'), r.get('dDir2Z'), 7),
                bbox=[fnum(r[k], 4) for k in ('xmin', 'ymin', 'zmin', 'xmax', 'ymax', 'zmax')] if r.get('xmin') is not None else None))
        out = []
        for r in D['eq']:
            eq = r['eq'].upper()
            so = r.get('sysoid')
            path = (M.system_path(so) + [M.systree['name'].get(so.upper(), '')]) if so else []
            rec = collections.OrderedDict()
            rec['oid'] = eq; rec['kind'] = 'equipment'; rec['name'] = (r.get('strName') or '').strip()
            rec['description'] = r.get('strDescription') or r.get('jdesc')
            rec['catalog_class'] = r.get('CatalogPartClass')
            rec['system_path'] = path; rec['area'] = area_of(path)
            rec['origin'] = xyz(r.get('o0'), r.get('o1'), r.get('o2'))
            rec['x_axis'] = xyz(r.get('x0'), r.get('x1'), r.get('x2'), 7)
            rec['y_axis'] = xyz(r.get('y0'), r.get('y1'), r.get('y2'), 7)
            rec['z_axis'] = xyz(r.get('z0'), r.get('z1'), r.get('z2'), 7)
            rec['bbox'] = [fnum(r[k], 4) for k in ('xmin', 'ymin', 'zmin', 'xmax', 'ymax', 'zmax')] if r.get('xmin') is not None else None
            rec['dry_weight'] = fnum(r.get('DryWeight'), 2); rec['wet_weight'] = fnum(r.get('WetWeight'), 2)
            rec['attributes'] = M.named_attrs(eattr.get(eq, []))
            rec['components'] = comps.get(eq, [])
            rec['nozzles'] = sorted(nozz.get(eq, []), key=lambda z: str(z['label']))
            rec['shapes'] = shapes.get(eq, [])
            rec['persistent_flag'] = r.get('pf')
            out.append(rec)
            tot['equipment'] += 1; tot['nozzles'] += len(rec['nozzles']); tot['shapes'] += len(rec['shapes'])
            tot['with_shapes'] += bool(rec['shapes']); tot['with_nozzles'] += bool(rec['nozzles'])
        write_json(fn, out)
        log('equip page %d: %d eq %.1fs' % (pi, len(out), time.time() - t))
    log('equip done %s' % dict(tot))


def merge():
    import ex_struct
    by_area = collections.defaultdict(list)
    allr = []
    for f in sorted(glob.glob(os.path.join(PDIR, '*.json.gz'))):
        allr += read_json(f)
    # equipment whose system chain does not reach a plant area: nearest assigned equipment (spatial)
    for r in allr:
        if r.get('origin') and not r.get('start'):
            r['start'] = r['origin']
    n = ex_struct.spatial_areas(allr, cell=25.0)
    log('equipment spatially assigned: %d' % n)
    for r in allr:
        r.pop('start', None)
        by_area[r['area']].append(r)
    od = os.path.join(OUT, 'json', 'equipment'); os.makedirs(od, exist_ok=True)
    summary = {}
    shape_types = collections.Counter()
    for area, recs in sorted(by_area.items()):
        fn = safe_name(area.replace('/', '__'), 100) + '.jsonl.gz'
        with gzip.open(os.path.join(od, fn + '.tmp'), 'wt', compresslevel=6) as f:
            for r in sorted(recs, key=lambda r: r['oid']):
                f.write(json.dumps(r, separators=(',', ':'), default=jdefault) + '\n')
        os.replace(os.path.join(od, fn + '.tmp'), os.path.join(od, fn))
        for r in recs:
            for s in r['shapes']:
                shape_types[s['shape_type']] += 1
        summary[area] = {'file': 'json/equipment/' + fn, 'equipment': len(recs), 'nozzles': sum(len(r['nozzles']) for r in recs),
                         'shapes': sum(len(r['shapes']) for r in recs), 'with_shapes': sum(1 for r in recs if r['shapes'])}
    json.dump({'areas': summary, 'shape_types': dict(shape_types)}, open(os.path.join(WORK, 'equip_summary.json'), 'w'), indent=1)
    log('equipment merged: %d areas' % len(summary))


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'run':
        run()
    elif cmd == 'merge':
        merge()
