"""Structure extraction: linear members (exact axis/section/roll/cardinal point) + curved members, slabs, footings (reference data only).

ex_struct.py pages   -> WORK/jobs/struct_pages.json (oid ranges of STRUCTMemberPartPris)
ex_struct.py run [--workers 4]
ex_struct.py merge   -> OUT/json/structure/<area>.jsonl.gz
"""
import os, sys, re, json, time, math, argparse, collections, gzip, glob, traceback
from common import *
from pipemap import Meta, area_of

PAGES = os.path.join(WORK, 'jobs', 'struct_pages.json')
PDIR = os.path.join(WORK, 'struct', 'pages')

MEMBER_SQL = """
SET NOCOUNT ON;
SELECT oid INTO #mp FROM dbo.STRUCTMemberPartPris WHERE oid > '%(LO)s' AND oid <= '%(HI)s';
CREATE CLUSTERED INDEX ix_mp ON #mp(oid);
SELECT CAST(mp.oid AS char(36)) mp, n.strName, b.persistentFlag pf, mp.typeCategory, mp.type, mp.cutLength, mp.weight,
  mp.cgx, mp.cgy, mp.cgz, mp.priority, CAST(g.oid AS char(36)) gen, pg.cardinalPoint, pg.aspect,
  ax.startx, ax.starty, ax.startz, ax.endx, ax.endy, ax.endz, ax.betaAngle, ax.OVectorx, ax.OVectory, ax.OVectorz, ax.mirror, ax.flag axflag,
  xs.RelationName section, mat.RelationName material, CAST(ms.oid AS char(36)) memsys, CAST(ss.oid AS char(36)) structsys,
  si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax
FROM #mp q JOIN dbo.STRUCTMemberPartPris mp ON mp.oid = q.oid
LEFT JOIN dbo.COREBaseClass b ON b.oid = mp.oid
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = mp.oid AND x.RelationType = '%(MemberToXS)s') g
LEFT JOIN dbo.STRUCTPartPrismaticGen pg ON pg.oid = g.oid
OUTER APPLY (SELECT TOP 1 a.* FROM dbo.CORERelationOrigin x JOIN dbo.STRUCTMemberPartAxisLin a ON a.oid = x.oidTarget
             WHERE x.oid = g.oid AND x.RelationType = '%(Operand)s') ax
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = '%(ProxyOwner)s'
             WHERE x.oid = g.oid AND x.RelationType = '%(DefinitionXS)s') xs
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = '%(ProxyOwner)s'
             WHERE x.oid = g.oid AND x.RelationType = '%(Material)s') mat
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = mp.oid AND x.RelationType = '%(DesignParent)s') ms
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = ms.oid AND x.RelationType = '%(SysParent)s') ss
LEFT JOIN dbo.CORENamedItem n ON n.oid = mp.oid
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = mp.oid;
DROP TABLE #mp;
"""

CURVE_SQL = """
SET NOCOUNT ON;
SELECT CAST(mp.oid AS char(36)) mp, n.strName, b.persistentFlag pf, mp.typeCategory, mp.type, mp.cutLength, mp.weight,
  CAST(g.oid AS char(36)) gen, pg.cardinalPoint,
  ax.startX, ax.startY, ax.startZ, ax.EndX, ax.EndY, ax.EndZ, ax.xAxisX, ax.xAxisY, ax.xAxisZ, ax.zAxisX, ax.zAxisY, ax.zAxisZ, ax.betaAngle, ax.mirror,
  xs.RelationName section, mat.RelationName material, CAST(ss.oid AS char(36)) structsys,
  si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax
FROM dbo.STRUCTMemberPartCurve mp
LEFT JOIN dbo.COREBaseClass b ON b.oid = mp.oid
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = mp.oid AND x.RelationType = '%(MemberToXS)s') g
LEFT JOIN dbo.STRUCTPartPrismaticGen pg ON pg.oid = g.oid
OUTER APPLY (SELECT TOP 1 a.* FROM dbo.CORERelationOrigin x JOIN dbo.STRUCTMembPartAxisCurve a ON a.oid = x.oidTarget
             WHERE x.oid = g.oid AND x.RelationType = '%(Operand)s') ax
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = '%(ProxyOwner)s'
             WHERE x.oid = g.oid AND x.RelationType = '%(DefinitionXS)s') xs
OUTER APPLY (SELECT TOP 1 po.RelationName FROM dbo.CORERelationOrigin x
             JOIN dbo.CORERelationOrigin po ON po.oidTarget = x.oidTarget AND po.RelationType = '%(ProxyOwner)s'
             WHERE x.oid = g.oid AND x.RelationType = '%(Material)s') mat
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = mp.oid AND x.RelationType = '%(DesignParent)s') ms
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = ms.oid AND x.RelationType = '%(SysParent)s') ss
LEFT JOIN dbo.CORENamedItem n ON n.oid = mp.oid
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = mp.oid;
"""

SLAB_SQL = """
SET NOCOUNT ON;
SELECT CAST(s.oid AS char(36)) oid, n.strName, b.persistentFlag pf, s.entityWeight, s.entityTotalVolume, s.entityNetVolume, s.entityTotalArea,
  s.entityNetArea, s.entityAngle, s.entityLowPoint, s.entityHighPoint, s.entityTOC, s.entityBOC, s.entityOpenings,
  CAST(p.oid AS char(36)) parent, si.xmin, si.ymin, si.zmin, si.xmax, si.ymax, si.zmax
FROM dbo.STRUCTSPSSlabEntity s
LEFT JOIN dbo.COREBaseClass b ON b.oid = s.oid
LEFT JOIN dbo.CORENamedItem n ON n.oid = s.oid
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = s.oid AND x.RelationType = '%(SystemHierarchy)s') p
LEFT JOIN dbo.CORESpatialIndex si ON si.oid = s.oid;
"""


def section_info(M, moniker):
    if not moniker:
        return None
    parts = [p.strip() for p in moniker.split(',')]
    std, typ, name = (parts + [None, None, None])[:3] if len(parts) >= 3 else (None, parts[0] if parts else None, parts[-1] if parts else None)
    dims = M.sections.get(moniker) or {}
    keep = ('Depth', 'Width', 'Area', 'Perimeter', 'UnitWeight', 'd', 'bf', 'tf', 'tw', 'kdesign', 'kdetail', 'tnom', 'tdes', 'b', 't', 'h',
            'xp', 'yp', 'x', 'y', 'bb', 'tb', 'LongLegSpacing', 'ShortLegSpacing', 'bfb', 'tfb', 'bft', 'tft', 'D_t', 'b_t', 'h_t', 'r', 'R', 'eo', 'xo', 'yo')
    dd = {k: fnum(v, 7) for k, v in dims.items() if not k.startswith('design.')}
    return {'moniker': moniker, 'standard': std, 'type': typ, 'name': name, 'dims': dd}


def xyz(a, b, c, nd=5):
    if a is None or b is None or c is None:
        return None
    return [round(float(a), nd), round(float(b), nd), round(float(c), nd)]


def member_rec(M, r, curved=False):
    path = M.system_path(r['structsys']) + ([M.systree['name'].get(r['structsys'].upper(), '')] if r.get('structsys') else []) if r.get('structsys') else []
    rec = collections.OrderedDict()
    rec['oid'] = r['mp'].upper()
    rec['kind'] = 'curved_member' if curved else 'member'
    rec['name'] = (r.get('strName') or '').strip()
    rec['category'] = M.cl('StructuralMemberTypeCategory', r.get('typeCategory'))
    rec['type'] = M.cl('StructuralMemberType', r.get('type'))
    rec['system_path'] = path
    rec['area'] = area_of(path)
    if curved:
        rec['start'] = xyz(r.get('startX'), r.get('startY'), r.get('startZ'))
        rec['end'] = xyz(r.get('EndX'), r.get('EndY'), r.get('EndZ'))
        rec['x_axis'] = xyz(r.get('xAxisX'), r.get('xAxisY'), r.get('xAxisZ'), 7)
        rec['z_axis'] = xyz(r.get('zAxisX'), r.get('zAxisY'), r.get('zAxisZ'), 7)
        rec['geometry_note'] = 'curved member: only start/end/frame are in columns; curve shape is in the ACIS wire body'
    else:
        rec['start'] = xyz(r.get('startx'), r.get('starty'), r.get('startz'))
        rec['end'] = xyz(r.get('endx'), r.get('endy'), r.get('endz'))
        rec['o_vector'] = xyz(r.get('OVectorx'), r.get('OVectory'), r.get('OVectorz'), 7)
        rec['priority'] = r.get('priority')
    rec['roll_deg'] = fnum(math.degrees(r['betaAngle']), 4) if r.get('betaAngle') is not None else None
    rec['mirror'] = r.get('mirror')
    rec['cardinal_point'] = r.get('cardinalPoint')
    rec['cut_length'] = fnum(r.get('cutLength'))
    rec['weight'] = fnum(r.get('weight'), 3)
    if r.get('cgx') is not None:
        rec['cg'] = xyz(r['cgx'], r['cgy'], r['cgz'])
    rec['section'] = section_info(M, r.get('section'))
    rec['material'] = r.get('material')
    if r.get('xmin') is not None:
        rec['bbox'] = [fnum(r[k], 4) for k in ('xmin', 'ymin', 'zmin', 'xmax', 'ymax', 'zmax')]
    rec['persistent_flag'] = r.get('pf')
    return rec


def make_pages(n):
    c = connect(MDB)
    cols, rows = query(c, "SELECT CAST(oid AS char(36)) FROM dbo.STRUCTMemberPartPris ORDER BY oid")
    oids = [r[0] for r in rows]
    pages = []
    lo = '00000000-0000-0000-0000-000000000000'
    for i in range(n - 1, len(oids), n):
        pages.append({'id': 'sp%04d' % len(pages), 'lo': lo, 'hi': oids[i]}); lo = oids[i]
    pages.append({'id': 'sp%04d' % len(pages), 'lo': lo, 'hi': 'FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF'})
    os.makedirs(os.path.dirname(PAGES), exist_ok=True)
    json.dump(pages, open(PAGES, 'w'))
    print('members', len(oids), 'pages', len(pages))


M = None


def _page(pg):
    c = connect(MDB)
    t = time.time()
    rows = dicts(query(c, MEMBER_SQL % dict(R, LO=pg['lo'], HI=pg['hi'])))
    recs = [member_rec(M, r) for r in rows]
    os.makedirs(PDIR, exist_ok=True)
    write_json(os.path.join(PDIR, pg['id'] + '.json.gz'), recs)
    c.close()
    return pg['id'], len(recs), round(time.time() - t, 1)


def run(workers):
    global M
    M = Meta()
    pages = [p for p in json.load(open(PAGES)) if not os.path.exists(os.path.join(PDIR, p['id'] + '.json.gz'))]
    log('struct pages to run: %d' % len(pages))
    import multiprocessing as mp
    with mp.get_context('fork').Pool(workers) as pool:
        for r in pool.imap_unordered(_page, pages):
            log('page %s %d members %.1fs' % r)
    # curved members + slabs (single queries)
    c = connect(MDB)
    if not os.path.exists(os.path.join(PDIR, 'curved.json.gz')):
        rows = dicts(query(c, CURVE_SQL % R))
        write_json(os.path.join(PDIR, 'curved.json.gz'), [member_rec(M, r, curved=True) for r in rows])
        log('curved members %d' % len(rows))
    if not os.path.exists(os.path.join(PDIR, 'slabs.json.gz')):
        rows = dicts(query(c, SLAB_SQL % R))
        out = []
        for r in rows:
            par = r.get('parent')
            path = (M.system_path(par) + [M.systree['name'].get(par.upper(), '')]) if par else []
            out.append(collections.OrderedDict(
                oid=r['oid'].upper(), kind='slab', name=(r.get('strName') or '').strip(), system_path=path, area=area_of(path),
                weight=fnum(r.get('entityWeight'), 2), volume=fnum(r.get('entityTotalVolume')), net_volume=fnum(r.get('entityNetVolume')),
                area_m2=fnum(r.get('entityTotalArea')), net_area_m2=fnum(r.get('entityNetArea')), angle=fnum(r.get('entityAngle')),
                low_point=fnum(r.get('entityLowPoint')), high_point=fnum(r.get('entityHighPoint')), toc=fnum(r.get('entityTOC')),
                boc=fnum(r.get('entityBOC')), openings=r.get('entityOpenings'),
                bbox=[fnum(r[k], 4) for k in ('xmin', 'ymin', 'zmin', 'xmax', 'ymax', 'zmax')] if r.get('xmin') is not None else None,
                geometry_note='slab outline only in ACIS body; bbox from CORESpatialIndex', persistent_flag=r.get('pf')))
        write_json(os.path.join(PDIR, 'slabs.json.gz'), out)
        log('slabs %d' % len(out))


_TOP = None


def top_areas():
    """names of the level-1 systems under the plant root (MLNG, MLNG DUA, UTILITY, TERMINAL, ...)"""
    global _TOP
    if _TOP is None:
        st = load_pkl('systree')
        roots = {r for r in set(st['par'].values()) - set(st['par']) if st['cls'].get(r) == 40005}
        _TOP = {st['name'].get(c) for c, p in st['par'].items() if p in roots and st['cls'].get(c) in (210010, 40007, 210005, 210006)}
    return _TOP


def _unknown(r):
    p = r.get('system_path') or []
    return (not p) or p == [''] or r.get('area') in ('/_', '_unassigned', '') or p[0] not in top_areas()


def spatial_areas(recs, cell=20.0):
    """assign an area to records without a system path from the majority area of nearby records"""
    grid = collections.defaultdict(collections.Counter)
    def pt(r):
        p = r.get('start') or (r.get('bbox') and [(r['bbox'][0] + r['bbox'][3]) / 2, (r['bbox'][1] + r['bbox'][4]) / 2, 0])
        return p
    for r in recs:
        if not _unknown(r):
            p = pt(r)
            if p:
                grid[(int(p[0] // cell), int(p[1] // cell))][r['area']] += 1
    n = 0
    for r in recs:
        if _unknown(r):
            p = pt(r)
            if not p:
                continue
            i, j = int(p[0] // cell), int(p[1] // cell)
            for rad in range(0, 6):
                c = collections.Counter()
                for a in range(-rad, rad + 1):
                    for b in range(-rad, rad + 1):
                        if max(abs(a), abs(b)) == rad:
                            c.update(grid.get((i + a, j + b), {}))
                if c:
                    r['area'] = c.most_common(1)[0][0]; r['area_source'] = 'spatial (nearest assigned members, %d m cells)' % cell; n += 1
                    break
            else:
                r['area'] = '_unassigned'
    return n


def merge():
    import memberfit
    by_area = collections.defaultdict(list)
    allr = []
    for f in sorted(glob.glob(os.path.join(PDIR, '*.json.gz'))):
        allr += read_json(f)
    log('spatially assigned areas: %d' % spatial_areas(allr))
    nfit = collections.Counter()
    for r in allr:
        if r['kind'] == 'member' and r.get('start'):
            e = memberfit.fit_extent(r)
            if e:
                r['extent'] = e; nfit['ok' if e['ok'] else 'rejected'] += 1
            else:
                nfit['nofit'] += 1
        by_area[r['area']].append(r)
    log('extent fits: %s' % dict(nfit))
    od = os.path.join(OUT, 'json', 'structure')
    os.makedirs(od, exist_ok=True)
    summary = {}
    for area, recs in sorted(by_area.items()):
        fn = safe_name(area.replace('/', '__'), 100) + '.jsonl.gz'
        tmp = os.path.join(od, fn + '.tmp')
        with gzip.open(tmp, 'wt', compresslevel=6) as f:
            for r in sorted(recs, key=lambda r: (r['kind'], r['oid'])):
                f.write(json.dumps(r, separators=(',', ':'), default=jdefault) + '\n')
        os.replace(tmp, os.path.join(od, fn))
        cnt = collections.Counter(r['kind'] for r in recs)
        summary[area] = {'file': 'json/structure/' + fn, 'counts': dict(cnt),
                         'with_axis': sum(1 for r in recs if r['kind'] == 'member' and r.get('start') and r.get('end')),
                         'with_section_dims': sum(1 for r in recs if r['kind'] == 'member' and r.get('section') and r['section']['dims'])}
    json.dump(summary, open(os.path.join(WORK, 'struct_summary.json'), 'w'), indent=1)
    tot = collections.Counter()
    for v in summary.values():
        tot.update(v['counts']); tot['with_axis'] += v['with_axis']; tot['with_section_dims'] += v['with_section_dims']
    log('structure merged: %d areas %s' % (len(summary), dict(tot)))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('--workers', type=int, default=4); ap.add_argument('--page', type=int, default=20000)
    a = ap.parse_args()
    if a.cmd == 'pages':
        make_pages(a.page)
    elif a.cmd == 'run':
        run(a.workers)
    elif a.cmd == 'merge':
        merge()
