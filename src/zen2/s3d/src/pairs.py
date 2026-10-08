"""Pairing index: our 3D/JSON/PCF outputs <-> Smart 3D's own drawings and documents (read-only SQL).

pairs.py extract   -> WORK/pairs/*.pkl   (sheets, documents, revisions, view->sheet, drawing-map aggregates)
pairs.py build     -> OUT/pairs/{pipelines,areas,drawings}.jsonl.gz + OUT/pairs/summary.json
"""
import os, sys, json, gzip, glob, time, pickle, collections
from common import *

PD = os.path.join(WORK, 'pairs')
REL = dict(SheetToDrawingTarget='2D56B54A-DE50-41D2-B573-C3849B200068', ObjectHasOutput='52683F7A-B404-47EA-9B56-2B672409B09F',
           MgrHasDataDocuments='123A40A9-E974-4B9E-A680-8E08C1D4B26B', SheetHasProperty='FC141B75-FFE9-4B2E-83D0-C72970CA98A2',
           SheetHasViews='047E42D0-6FD5-11D4-B28F-00104BCC2DC1', SnapInHasSheets='379F0A03-015E-4924-B298-76C899341639',
           PropertiesHasRevisions='16E79AC7-C5B1-44FD-B782-2B0F653BFE66')
MDIDX = 'cad-disk-extract/zenitude-data-2/model_drawings/_index/'


def q(c, sql, **kw):
    t = time.time()
    cols, rows = query(c, sql % dict(REL, **kw))
    log('  %d rows %.1fs %s' % (len(rows), time.time() - t, sql.strip().split('\n')[0][:80]))
    return [dict(zip(cols, r)) for r in rows]


def extract():
    os.makedirs(PD, exist_ok=True)
    c = connect(MDB)
    sheets = q(c, """
SELECT CAST(s.oid AS char(36)) sheet, s.FileName, s.TimeLastUpdated, s.UpToDate, s.IsBlank, n.strName sheet_name,
       CAST(t.oidTarget AS char(36)) target, bt.ClassId target_cls, tn.strName target_name,
       CAST(si.oidTarget AS char(36)) snapin, bs.ClassId snapin_cls, sn.strName snapin_name,
       CAST(po.oid AS char(36)) propobj, p.TimeCreated, p.TimeModified, p.ApprovedBy, p.ApprovedDate, p.CheckedBy, p.CheckedDate,
       p2.DrawingStatus, p2.PlantNumber, CAST(mg.oid AS char(36)) mgr
FROM dbo.DRAWNGDrawingSheet s
LEFT JOIN dbo.CORENamedItem n ON n.oid = s.oid
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = s.oid AND x.RelationType = '%(SheetToDrawingTarget)s') t
LEFT JOIN dbo.COREBaseClass bt ON bt.oid = t.oidTarget
LEFT JOIN dbo.CORENamedItem tn ON tn.oid = t.oidTarget
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = s.oid AND x.RelationType = '%(SnapInHasSheets)s') si
LEFT JOIN dbo.COREBaseClass bs ON bs.oid = si.oidTarget
LEFT JOIN dbo.CORENamedItem sn ON sn.oid = si.oidTarget
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = s.oid AND x.RelationType = '%(SheetHasProperty)s') po
LEFT JOIN dbo.DRAWNGPropertyObject p ON p.oid = po.oid
LEFT JOIN dbo.DRAWNGPropertyObject2 p2 ON p2.oid = po.oid
OUTER APPLY (SELECT TOP 1 x.oid FROM dbo.CORERelationOrigin x WHERE x.oidTarget = s.oid AND x.RelationType = '%(ObjectHasOutput)s') mg""")
    pickle.dump(sheets, open(os.path.join(PD, 'sheets.pkl'), 'wb'))
    docs = q(c, """
SELECT CAST(r.oid AS char(36)) mgr, CAST(d.oid AS char(36)) doc, r.RelationName rel, d.FileName, d.FileType, d.FileSize, d.RelationID, d.Description
FROM dbo.CORERelationOrigin r WITH (INDEX(CORERelationOriginTypeIndex))
JOIN dbo.DRAWNGDocumentData d ON d.oid = r.oidTarget
WHERE r.RelationType = '%(MgrHasDataDocuments)s'""")
    alld = q(c, "SELECT CAST(oid AS char(36)) doc, FileName, FileType, FileSize FROM dbo.DRAWNGDocumentData")
    mgr_target = q(c, """
SELECT CAST(x.oid AS char(36)) mgr, CAST(x.oidTarget AS char(36)) target, b.ClassId target_cls, n.strName target_name
FROM dbo.CORERelationOrigin x WITH (INDEX(CORERelationOriginTypeIndex))
LEFT JOIN dbo.COREBaseClass b ON b.oid = x.oidTarget LEFT JOIN dbo.CORENamedItem n ON n.oid = x.oidTarget
WHERE x.RelationType = '%(ObjectHasOutput)s'""")
    pickle.dump({'docs': docs, 'all': alld, 'mgr_target': mgr_target}, open(os.path.join(PD, 'docs.pkl'), 'wb'))
    revs = q(c, """
SELECT CAST(rv.oid AS char(36)) rev, rv.RevMark, rv.RevDate, rv.RevDesc, rv.RevVersion, rv.RevRecordType, rv.RevChkBy, rv.RevAppBy, rv.RevRevBy,
       CAST(rp.oidTarget AS char(36)) revprops, CAST(pc.oidTarget AS char(36)) propobj
FROM dbo.DRAWNGDwgRevision rv
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = rv.oid AND x.RelationType = '%(PropertiesHasRevisions)s') rp
OUTER APPLY (SELECT TOP 1 x.oidTarget FROM dbo.CORERelationOrigin x WHERE x.oid = rp.oidTarget AND x.RelationType =
             (SELECT TOP 1 RelationGUID FROM [MLNG@1_CDB_SCHEMA].dbo.RelationInfoView WHERE RelationName = 'PropertyHasChildren')) pc""")
    pickle.dump(revs, open(os.path.join(PD, 'revs.pkl'), 'wb'))
    views = q(c, """
SELECT CAST(x.oid AS char(36)) view_, CAST(x.oidTarget AS char(36)) sheet, v.ViewNames, v.Scale
FROM dbo.CORERelationOrigin x WITH (INDEX(CORERelationOriginTypeIndex))
LEFT JOIN dbo.DRAWNGDrawingView v ON v.oid = x.oid
WHERE x.RelationType = '%(SheetHasViews)s'""")
    pickle.dump(views, open(os.path.join(PD, 'views.pkl'), 'wb'))
    # drawing map: view -> 3D objects, streamed and aggregated by (view, class prefix); raw pairs kept for non-iso views only
    iso_sheets = {s['sheet'] for s in sheets if s['target_cls'] == 210007}
    v2s = {v['view_'].upper(): v['sheet'].upper() for v in views}
    cur = c.cursor()
    cur.execute("SELECT CAST(strViewDBID AS char(36)), CAST(str3D_DBID AS char(36)) FROM dbo.DRAWNGDrawingMap")
    n = 0; per_sheet = collections.defaultdict(set)
    while True:
        rows = cur.fetchmany(200000)
        if not rows:
            break
        for v, o in rows:
            n += 1
            sh = v2s.get(v.upper())
            if sh and sh not in iso_sheets and o:
                per_sheet[sh].add(o.upper())
    log('drawing map rows %d, non-iso sheets with objects %d' % (n, len(per_sheet)))
    pickle.dump({k: sorted(v) for k, v in per_sheet.items()}, open(os.path.join(PD, 'map_noniso.pkl'), 'wb'))


def load_mdidx():
    """lead's export index: doc oid -> keys (and key -> #oids sharing it)"""
    import boto3
    s3 = boto3.client('s3')
    doc_keys, key_cnt = {}, collections.Counter()
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET, Prefix=MDIDX):
        for o in page.get('Contents', []):
            body = s3.get_object(Bucket=S3_BUCKET, Key=o['Key'])['Body'].read()
            for line in gzip.decompress(body).decode().splitlines():
                r = json.loads(line)
                ks = [x['key'] for x in r.get('objects') or []]
                doc_keys[r['oid'].upper()] = ks
                for k in ks:
                    key_cnt[k] += 1
    return doc_keys, key_cnt


def build():
    sheets = pickle.load(open(os.path.join(PD, 'sheets.pkl'), 'rb'))
    D = pickle.load(open(os.path.join(PD, 'docs.pkl'), 'rb'))
    revs = pickle.load(open(os.path.join(PD, 'revs.pkl'), 'rb'))
    mapn = pickle.load(open(os.path.join(PD, 'map_noniso.pkl'), 'rb'))
    doc_keys, key_cnt = load_mdidx()
    log('export index: %d docs, %d keys' % (len(doc_keys), len(key_cnt)))
    docs_by_mgr = collections.defaultdict(list)
    for d in D['docs']:
        docs_by_mgr[d['mgr'].upper()].append(d)
    revs_by_po = collections.defaultdict(list)
    for r in revs:
        if r.get('propobj'):
            revs_by_po[r['propobj'].upper()].append(r)

    def doc_rec(d):
        ks = doc_keys.get(d['doc'].upper())
        return {'oid': d['doc'].upper(), 'file_name': d['FileName'], 'type': (d['FileType'] or '').lower(), 'size': d['FileSize'],
                'role': d.get('rel'), 's3_keys': ks, 'exported': ks is not None,
                'key_shared_by_docs': max((key_cnt[k] for k in ks), default=0) if ks else None}

    def sheet_rec(s):
        po = (s.get('propobj') or '').upper()
        rv = sorted(revs_by_po.get(po, []), key=lambda r: (r.get('RevVersion') or 0))
        return collections.OrderedDict(
            sheet=s['sheet'].upper(), file_name=s['FileName'], name=s.get('sheet_name'), updated=s['TimeLastUpdated'],
            up_to_date=s.get('UpToDate'), drawing=(s.get('snapin') or '').upper() or None, drawing_name=s.get('snapin_name'),
            drawing_cls=s.get('snapin_cls'), created=s.get('TimeCreated'), modified=s.get('TimeModified'),
            approved_by=s.get('ApprovedBy'), approved_date=s.get('ApprovedDate'), checked_by=s.get('CheckedBy'),
            status=s.get('DrawingStatus'),
            revisions=[{'mark': r['RevMark'], 'date': r['RevDate'], 'desc': r['RevDesc'], 'version': r['RevVersion'],
                        'checked': r.get('RevChkBy'), 'approved': r.get('RevAppBy')} for r in rv],
            documents=[doc_rec(d) for d in docs_by_mgr.get((s.get('mgr') or '').upper(), [])])

    # ---- our side
    pl_out = {}
    for f in glob.glob(os.path.join(WORK, 'done', 'piping', 'pb*.json')):
        for r in json.load(open(f))['results']:
            if 'error' not in r:
                pl_out[r['pl'].upper()] = r
    jobs = json.load(open(os.path.join(WORK, 'jobs', 'ifc.json')))
    chunks_by_json = collections.defaultdict(list); area_chunks = collections.defaultdict(list)
    for j in jobs:
        base = 'ifc/%s/%s' % (safe_name((j.get('area') or '').replace('/', '__'), 90), j['id']) if j['kind'] == 'piping' else None
        man_p = os.path.join(WORK, 'ifcdone', j['id'] + '.json')
        if os.path.exists(man_p):
            m = json.load(open(man_p)); base = m['ifc'][:-4]; area = m['area']
        else:
            area = j.get('area')
        files = {'id': j['id'], 'kind': j['kind'], 'ifc': base + '.ifc', 'step': base.replace('ifc/', 'step/', 1) + '.step',
                 'glb': base.replace('ifc/', 'gltf/', 1) + '.glb', 'obj': base.replace('ifc/', 'obj/', 1) + '.obj'}
        if j.get('part'):
            files['part'] = j['part']
        for inp in j.get('inputs', []):
            chunks_by_json[inp].append(files)
        area_chunks[area].append(files)
    # object -> (area, discipline, owner) for drawing coverage
    log('loading object->area map')
    obj_area = {}
    for f in glob.glob(os.path.join(OUT, 'json', 'structure', '*.jsonl.gz')):
        for line in gzip.open(f, 'rt'):
            r = json.loads(line)
            obj_area[r['oid']] = (r['area'], 'structure')
    for f in glob.glob(os.path.join(OUT, 'json', 'equipment', '*.jsonl.gz')):
        for line in gzip.open(f, 'rt'):
            r = json.loads(line)
            obj_area[r['oid']] = (r['area'], 'equipment')
            for z in r.get('nozzles') or []:
                obj_area[z['oid']] = (r['area'], 'equipment')
    for pl, r in pl_out.items():
        obj_area[pl] = (r['area'], 'piping')
    for pl, r in pl_out.items():
        try:
            J = read_json(os.path.join(OUT, r['json']))
        except Exception:
            continue
        for C in J['components']:
            obj_area[C['oid']] = (r['area'], 'piping')
        for S in J.get('supports', []):
            obj_area[S['oid']] = (r['area'], 'supports')
            for sc in S.get('components') or []:
                obj_area[sc['oid']] = (r['area'], 'supports')
    log('object map %d' % len(obj_area))

    od = os.path.join(OUT, 'pairs'); os.makedirs(od, exist_ok=True)
    by_pl = collections.defaultdict(list)
    for s in sheets:
        if s.get('target_cls') == 210007 and s.get('target'):
            by_pl[s['target'].upper()].append(s)
    summ = collections.Counter()
    pinfo = {d['oid'].upper(): d for d in load_pkl('pipelines')}
    with gzip.open(os.path.join(od, 'pipelines.jsonl.gz.tmp'), 'wt') as f:
        for pl in sorted(set(pinfo) | set(by_pl)):
            r = pl_out.get(pl)
            ours = None
            if r:
                ours = {'json': r['json'], 'pcf': r['pcf_file'], 'area': r['area'], 'components': r['n'],
                        'ifc_chunks': chunks_by_json.get(r['json'], [])}
            shs = [sheet_rec(s) for s in sorted(by_pl.get(pl, []), key=lambda s: str(s['TimeLastUpdated']))]
            types = collections.Counter(d['type'] for s in shs for d in s['documents'])
            rec = collections.OrderedDict(pipeline=pl, name=(pinfo.get(pl, {}).get('strName') or (shs[0]['file_name'] if shs else '')).strip(),
                                          ours=ours, s3d_iso_sheets=shs, s3d_document_types=dict(types))
            f.write(json.dumps(rec, default=str) + '\n')
            summ['pipelines'] += 1; summ['pipelines_with_iso'] += bool(shs); summ['iso_sheets'] += len(shs)
            summ['pipelines_with_s3d_pcf'] += types.get('pcf', 0) > 0; summ['pipelines_with_sha'] += types.get('sha', 0) > 0
            summ['pipelines_with_pod'] += types.get('pod', 0) > 0; summ['pipelines_with_xml'] += types.get('xml', 0) > 0
            summ['pipelines_with_our_files'] += ours is not None
    os.replace(os.path.join(od, 'pipelines.jsonl.gz.tmp'), os.path.join(od, 'pipelines.jsonl.gz'))
    # drawings (all sheets) + per-area coverage for non-iso drawings
    area_dw = collections.defaultdict(list)
    with gzip.open(os.path.join(od, 'drawings.jsonl.gz.tmp'), 'wt') as f:
        for s in sheets:
            rec = sheet_rec(s)
            rec['target'] = (s.get('target') or '').upper() or None
            rec['target_cls'] = s.get('target_cls'); rec['target_name'] = s.get('target_name')
            objs = mapn.get(s['sheet'].upper(), [])
            cov = collections.Counter(); disc = collections.Counter()
            for o in objs:
                a = obj_area.get(o)
                if a:
                    cov[a[0]] += 1; disc[a[1]] += 1
            rec['objects_shown'] = len(objs) if objs else None
            rec['objects_by_area'] = dict(cov.most_common(20)) if cov else None
            rec['objects_by_discipline'] = dict(disc) if disc else None
            rec['kind'] = 'isometric' if s.get('target_cls') == 210007 else ('orthographic/3D' if objs else 'other')
            f.write(json.dumps(rec, default=str) + '\n')
            summ['sheets'] += 1; summ['sheets_' + rec['kind']] += 1
            for a, nobj in cov.items():
                area_dw[a].append({'sheet': rec['sheet'], 'file_name': rec['file_name'], 'drawing_name': rec['drawing_name'],
                                   'objects_in_area': nobj, 'objects_by_discipline': rec['objects_by_discipline'], 'updated': rec['updated'],
                                   'revisions': rec['revisions'][-1:] if rec['revisions'] else [],
                                   'documents': [d for d in rec['documents'] if d['type'] in ('sha', 'pdf', 'dwg', 'xml', 'sat')][:20]})
    os.replace(os.path.join(od, 'drawings.jsonl.gz.tmp'), os.path.join(od, 'drawings.jsonl.gz'))
    ss = json.load(open(os.path.join(WORK, 'struct_summary.json')))
    es = json.load(open(os.path.join(WORK, 'equip_summary.json')))['areas']
    with gzip.open(os.path.join(od, 'areas.jsonl.gz.tmp'), 'wt') as f:
        for a in sorted(set(area_chunks) | set(area_dw) | set(ss) | set(es)):
            rec = collections.OrderedDict(area=a, structure_json=(ss.get(a) or {}).get('file'), equipment_json=(es.get(a) or {}).get('file'),
                                          our_chunks=area_chunks.get(a, []),
                                          s3d_drawings=sorted(area_dw.get(a, []), key=lambda x: -x['objects_in_area']))
            f.write(json.dumps(rec, default=str) + '\n')
            summ['areas'] += 1; summ['areas_with_s3d_drawings'] += bool(area_dw.get(a))
    os.replace(os.path.join(od, 'areas.jsonl.gz.tmp'), os.path.join(od, 'areas.jsonl.gz'))
    dt = collections.Counter((d['FileType'] or '').lower() for d in D['all'])
    attached = {d['doc'].upper() for d in D['docs']}
    summ_out = {'generated': utcnow(), 'counts': dict(summ), 'documents_total': len(D['all']), 'documents_by_type': dict(dt),
                'documents_attached_to_output_managers': len(attached), 'documents_in_export_index': len(doc_keys),
                'export_keys_shared_by_several_docs': sum(1 for k, v in key_cnt.items() if v > 1),
                'files': {'pipelines': 'pairs/pipelines.jsonl.gz', 'drawings': 'pairs/drawings.jsonl.gz', 'areas': 'pairs/areas.jsonl.gz'},
                'notes': ['iso sheets link to pipelines via SheetToDrawingTarget; documents via CDocOutputMgr (ObjectHasOutput / MgrHasDataDocuments)',
                          'revisions: CDwgRevision -> DwgRevisionProperties -> CDwgPropertyObject -> sheet',
                          'orthographic/3D drawings: DRAWNGDrawingMap view -> 3D object, aggregated to our areas/disciplines',
                          's3_keys come from model_drawings/_index; key_shared_by_docs > 1 means the export key collides (object may hold another document)']}
    write_json(os.path.join(od, 'summary.json'), summ_out, gz=False)
    log('pairs: %s' % json.dumps(summ_out['counts']))


if __name__ == '__main__':
    {'extract': extract, 'build': build}[sys.argv[1]]()
