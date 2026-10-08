"""Collect fan-out conversion results from S3 -> WORK/convert_summary.json, WORK/conversions.json and refresh OUT/json/index.json."""
import os, json, collections, concurrent.futures as cf
import boto3
from common import *

PRE = 'cad-disk-extract/zenitude-data-2/_state/s3d3d/'


def main():
    s3 = boto3.client('s3')
    keys = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET, Prefix=PRE + 'results/'):
        keys += [o['Key'] for o in page.get('Contents', [])]

    def get(k):
        try:
            return json.loads(s3.get_object(Bucket=S3_BUCKET, Key=k)['Body'].read())
        except Exception as e:
            return {'id': k.rsplit('/', 1)[-1][:-5], 'error': 'unreadable result: %s' % e}
    with cf.ThreadPoolExecutor(32) as ex:
        res = list(ex.map(get, keys))
    jobs = json.loads(s3.get_object(Bucket=S3_BUCKET, Key='cad-disk-extract/zenitude-data-2/_control/s3d3d/jobs.json')['Body'].read())
    chunk_ids = {j['id'] for j in jobs if j['kind'] != 'area_png'}
    agg = collections.Counter(); byk = collections.defaultdict(collections.Counter); fails = []; hosts = collections.Counter()
    conv = {}
    for r in res:
        if r.get('kind') == 'area_png':
            agg['area_png_jobs'] += 1; agg['png'] += len((r.get('png') or {}).get('keys', [])); continue
        conv[r['id']] = r
        hosts[r.get('host')] += 1
        if 'error' in r:
            fails.append({'id': r['id'], 'reason': r['error'][:300]}); agg['errors'] += 1; continue
        k = r.get('kind')
        for x in ('step', 'glb', 'obj'):
            if x in r:
                ok = r[x].get('ok')
                agg[x + ('_ok' if ok else '_fail')] += 1; byk[k][x + ('_ok' if ok else '_fail')] += 1
                agg[x + '_bytes'] += r[x].get('bytes') or 0
                if not ok:
                    fails.append({'id': r['id'], 'reason': '%s failed: %s' % (x, (r[x].get('err') or '')[:200])})
        st = r.get('step') or {}
        agg['step_parts'] += st.get('parts') or 0; agg['step_faces'] += st.get('faces') or 0
        agg['ifc_elements'] += r.get('elements') or 0
        v = r.get('validate') or {}
        if v.get('read_status') == 'ok':
            agg['occ_read_ok'] += 1; byk[k]['occ_read_ok'] += 1
            agg['occ_transferred'] += v.get('transferred') or 0; agg['occ_solids'] += v.get('solids') or 0; agg['occ_faces'] += v.get('faces') or 0
            if v.get('roots_match_parts'):
                agg['occ_roots_eq_parts'] += 1
            else:
                fails.append({'id': r['id'], 'reason': 'OCC roots %s != parts %s' % (v.get('transferred'), st.get('parts'))})
        elif v.get('skipped'):
            agg['occ_skipped_size'] += 1
        elif v:
            agg['occ_read_fail'] += 1; fails.append({'id': r['id'], 'reason': 'OCC read-back: %s' % str(v)[:200]})
        g = r.get('glb') or {}
        agg['glb_meshes'] += g.get('meshes') or 0; agg['glb_triangles'] += g.get('triangles') or 0
        if g.get('meshes') is not None and r.get('elements') is not None and g['meshes'] != r['elements']:
            agg['glb_meshes_ne_elements'] += 1
    missing = sorted(chunk_ids - set(conv))
    out = {'generated': utcnow(), 'chunk_jobs': len(chunk_ids), 'results': len(conv), 'missing': len(missing), 'missing_ids': missing[:50],
           'totals': {k: (round(v / 1e9, 2) if k.endswith('_bytes') else v) for k, v in agg.items()},
           'bytes_unit': 'GB for *_bytes', 'by_kind': {k: dict(v) for k, v in byk.items()}, 'hosts': dict(hosts), 'failures': fails[:200]}
    json.dump(out, open(os.path.join(WORK, 'convert_summary.json'), 'w'), indent=1)
    json.dump(conv, open(os.path.join(WORK, 'conversions.json'), 'w'))
    print(json.dumps({k: out[k] for k in ('chunk_jobs', 'results', 'missing', 'totals', 'by_kind')}, indent=1))
    print('failures', len(fails), fails[:5])


if __name__ == '__main__':
    main()
