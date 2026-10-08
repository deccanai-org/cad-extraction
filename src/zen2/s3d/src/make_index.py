"""OUT/json/index.json : catalogue of every produced file (paths relative to s3://annotationprod/cad-disk-extract/zenitude-data-2/model/)."""
import os, json, glob, collections
from common import *


def main():
    idx = collections.OrderedDict()
    idx['schema'] = 's3d-index/1'
    idx['generated'] = utcnow()
    idx['source'] = 'Hexagon Smart 3D v13 model MLNG@1 (MLNG@1_MDB / MLNG@1_CDB), extracted without an S3D licence'
    idx['s3_root'] = 's3://%s/%s/' % (S3_BUCKET, S3_PREFIX)
    idx['units'] = {'json': 'metres, radians/degrees as named, global S3D frame X east / Y north / Z up',
                    'pcf': 'coordinates mm, bores mm (DN)', 'ifc': 'metres, local origin per file (IfcMapConversion + S3D_LocalOrigin pset)'}
    pls = []
    for f in sorted(glob.glob(os.path.join(WORK, 'done', 'piping', 'pb*.json'))):
        for r in json.load(open(f)).get('results', []):
            if 'error' in r:
                continue
            pls.append({'name': r['name'], 'oid': r['pl'], 'area': r['area'], 'json': r['json'], 'pcf': r['pcf_file'],
                        'components': r['n'], 'counts': {k: v for k, v in r['counts'].items() if not k.startswith('_')},
                        'supports': r['counts'].get('_supports', 0), 'bbox': r.get('bbox'),
                        'checks': {k: r['checks'].get(k) for k in ('point_count_fail', 'connection_gap_fail', 'bore_mismatch', 'open_ports')},
                        'pcf_points_dangling': r['pcf'].get('points_dangling')})
    idx['pipelines'] = sorted(pls, key=lambda p: (p['area'], p['name']))
    ss = json.load(open(os.path.join(WORK, 'struct_summary.json'))) if os.path.exists(os.path.join(WORK, 'struct_summary.json')) else {}
    idx['structure'] = [dict(area=a, **v) for a, v in sorted(ss.items())]
    es = json.load(open(os.path.join(WORK, 'equip_summary.json'))) if os.path.exists(os.path.join(WORK, 'equip_summary.json')) else {}
    idx['equipment'] = [dict(area=a, **v) for a, v in sorted(es.get('areas', {}).items())]
    idx['equipment_shape_types'] = es.get('shape_types')
    ifc = []
    for f in sorted(glob.glob(os.path.join(WORK, 'ifcdone', '*.json'))):
        m = json.load(open(f))
        base = m['ifc'][4:-4]
        ifc.append({'id': m['id'], 'kind': m['kind'], 'area': m['area'], 'ifc': m['ifc'], 'bytes': m['bytes'], 'elements': m['elements'],
                    'origin': m['origin'], 'by_class': m['by_class'], 'step': 'step/%s.step' % base, 'glb': 'gltf/%s.glb' % base,
                    'obj': 'obj/%s.obj' % base, 'png': 'png/%s__iso_ne.png' % base})
    cp = os.path.join(WORK, 'conversions.json')
    if os.path.exists(cp):
        conv = json.load(open(cp))
        for e in ifc:
            r = conv.get(e['id'])
            if not r:
                e['conversion'] = 'pending'; continue
            e['conversion'] = {'step_ok': (r.get('step') or {}).get('ok'), 'step_bytes': (r.get('step') or {}).get('bytes'),
                               'step_parts': (r.get('step') or {}).get('parts'), 'occ_read': (r.get('validate') or {}).get('read_status') or (r.get('validate') or {}).get('skipped'),
                               'occ_roots': (r.get('validate') or {}).get('transferred'), 'glb_ok': (r.get('glb') or {}).get('ok'),
                               'glb_triangles': (r.get('glb') or {}).get('triangles'), 'obj_ok': (r.get('obj') or {}).get('ok'), 'error': r.get('error')}
    idx['ifc_files'] = ifc
    for n in ('ifc_summary', 'convert_summary', 'fanout'):
        p = os.path.join(WORK, n + '.json')
        if os.path.exists(p):
            idx[n] = json.load(open(p))
    try:
        import agg_piping
        s = agg_piping.summary()
        idx['piping_validation'] = {k: s[k] for k in ('pipelines_ok', 'pipelines_error', 'checks', 'pcf', 'types')}
    except Exception as e:
        idx['piping_validation'] = {'error': str(e)}
    write_json(os.path.join(OUT, 'json', 'index.json'), idx, gz=False)
    print('index: %d pipelines, %d structure areas, %d equipment areas, %d ifc files' % (len(pls), len(idx['structure']), len(idx['equipment']), len(ifc)))


if __name__ == '__main__':
    main()
