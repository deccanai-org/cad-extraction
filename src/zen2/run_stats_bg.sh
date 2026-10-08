pkill -f /work/stats_agg.py; sleep 1; cat > /work/stats_agg.py <<'__EOF__'
"""stats_agg.py - in-region aggregation of extraction statistics (runs on cad-zen2-files, loops every 60 s).

Z4: reads every per-archive manifest (_state/manifests/<id>.jsonl.gz, cached locally) + result, and writes
  _state/stats/ext_summary.json   (by extension / category: files, bytes, stored files/bytes; max nesting depth)
  _state/stats/archives.json      (per archive: path, size, files, stored, top types, status) - PRIVATE (has names)
Z2: file types of the source drawing set and of the unpacked SharedContent -> zenitude-data-2/_state/stats/ext_summary.json
"""
import gzip, json, os, time, collections
from concurrent.futures import ThreadPoolExecutor
import boto3

B = 'annotationprod'
Z4 = 'cad-disk-extract/zentitude-data-4'
Z2 = 'cad-disk-extract/zenitude-data-2'
CACHE = '/work/stats_cache'
os.makedirs(CACHE, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1')

CATS = {
    '3D model': 'stp step ifc ifczip ifcxml db1 db2 nwd nwc nwf rvt rfa skp 3dm sat igs iges stl obj glb gltf fbx 3ds dgn tbp tsep tczip tsc sdnf sldprt sldasm ipt iam jt x_t xml3d',
    'Tekla model files': 'tsfodat db dbx ifo tsc tpl inp dat mdl lock uselock history',
    '2D drawing': 'dwg dxf dg dpm dwf dwfx plt sha sym igr',
    'PDF': 'pdf',
    'CNC / fabrication': 'nc1 nc dstv kss xsr kiss abm bom',
    'Office / text': 'doc docx xls xlsx xlsm csv txt rtf msg eml ppt pptx odt ods htm html xml json ini cfg log',
    'Images / video': 'jpg jpeg png tif tiff bmp gif mp4 avi mov wmv mts heic',
    'Archives': 'zip 7z rar tar gz tgz bz2 xz cab',
    'Scripts / executables': 'py exe dll msi bat cmd vbs ps1 js',
}
EXT2CAT = {e: c for c, es in CATS.items() for e in es.split()}


def ext_of(path):
    base = path.rsplit('/', 1)[-1].lower()
    if '.' not in base:
        return '(none)'
    e = base.rsplit('.', 1)[-1]
    if len(e) > 12 or not e.replace('_', '').isalnum():
        return '(other)'
    if len(e) == 4 and e[0] in 'jmp' and e[1:].isdigit():   # Tekla attribute files .j123/.m123/.p123
        return e[0] + '###'
    if e.startswith('p_'):
        return 'p_*'
    return e


def cat_of(e):
    if e in ('j###', 'm###', 'p_*'):
        return 'Tekla model files'
    return EXT2CAT.get(e, 'Other')


def list_keys(prefix):
    out, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=prefix)
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += r.get('Contents', [])
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


import pickle, re
NESTED_MARK = re.compile(r'\.(zip|7z|rar|tar|tgz|gz|bz2|xz|cab)!/', re.I)   # our marker for unpacked nested archives
G = {'done': set(), 'by_ext': collections.defaultdict(lambda: [0, 0, set(), 0, 0, set()]), 'arch': {}}   # raw, bytes, uniq, ubytes, in_disk12_raw, in_disk12_uniq
import array as _array, bisect as _bisect
IDX = _array.array('Q')


def in_disk12(h):
    if not len(IDX):
        IDX.frombytes(s3.get_object(Bucket=B, Key=f'{Z4}/_control/disk12_sha64.bin')['Body'].read())
    i = _bisect.bisect_left(IDX, h)
    return i < len(IDX) and IDX[i] == h


def load_manifest(jid):
    """Compact per-archive data cached on local disk: ([(ext, size, sha64)], top_level_file_count)."""
    cf = f'{CACHE}/{jid}.v3.pkl'
    if os.path.exists(cf):
        return pickle.load(open(cf, 'rb'))
    body = gzip.decompress(s3.get_object(Bucket=B, Key=f'{Z4}/_state/manifests/{jid}.jsonl.gz')['Body'].read())
    rows, top = [], 0
    for line in body.splitlines():
        if line:
            e = json.loads(line)
            rows.append((ext_of(e['path']), e['size'], int(e['sha256'][:16], 16)))
            if not NESTED_MARK.search(e['path']):
                top += 1
    out = (rows, top)
    pickle.dump(out, open(cf, 'wb'), protocol=4)
    return out


def z4_round():
    res = {o['Key'].rsplit('/', 1)[-1][:-5]: o for o in list_keys(f'{Z4}/_state/results/') if o['Key'].endswith('.json')}
    mans = {o['Key'].rsplit('/', 1)[-1].split('.')[0] for o in list_keys(f'{Z4}/_state/manifests/')}
    new_ids = [j for j in res if j in mans and j not in G['done']]
    with ThreadPoolExecutor(16) as ex:
        rows_list = list(ex.map(load_manifest, new_ids))
        results = list(ex.map(lambda j: json.loads(s3.get_object(Bucket=B, Key=res[j]['Key'])['Body'].read()), new_ids))
    rep = G.setdefault('report', json.loads(s3.get_object(Bucket=B, Key=f'{Z4}/_control/report_archives.json')['Body'].read()))
    for jid, (rows, top), r in zip(new_ids, rows_list, results):
        per = collections.Counter()
        for e, size, h in rows:
            x = G['by_ext'][e]
            x[0] += 1; x[1] += size
            if h not in x[2]:
                x[2].add(h); x[3] += size
            if size > 0 and in_disk12(h):
                x[4] += 1; x[5].add(h)
            per[e] += 1
        md = max([n.get('depth', 0) for n in r.get('nested', [])] or [0])
        G['arch'][jid] = {'path': r['source'].split('/', 4)[-1], 'size': r.get('size'), 'status': r['status'], 'files': r['files'],
                          'stored_files': r.get('stored_files'), 'bytes': r['bytes'], 'nested': r.get('nested_count'),
                          'encrypted_nested': r.get('encrypted_nested'), 'max_depth': md, 'finished': r.get('finished'),
                          'top_types': per.most_common(6),
                          'model_files': {e: per[e] for e in ('ifc', 'ifczip', 'stp', 'step', 'db1', 'nwd', 'rvt', 'dwg', 'dxf', 'nc1') if per[e]},
                          'top_level_files': top}
        src_key = r['source'].split('/', 3)[-1]
        rr = rep.get(src_key)
        G['arch'][jid]['report_files'] = rr['files'] if rr else None
        G['arch'][jid]['verify'] = ('no_report_entry' if not rr else 'match' if rr['files'] == top else
                                   'more_than_report' if top > rr['files'] else 'fewer_than_report')
        G['done'].add(jid)
    by_ext = {e: [v[0], v[1], len(v[2]), v[3], v[4], len(v[5])] for e, v in G['by_ext'].items()}
    by_cat = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for e, v in by_ext.items():
        t = by_cat[cat_of(e)]
        for i in range(6):
            t[i] += v[i]
    fmt = lambda d: [{'type': k, 'files': v[0], 'bytes': v[1], 'stored_files': v[2], 'stored_bytes': v[3],
                      'in_disk12_files': v[4], 'in_disk12_unique': v[5]} for k, v in sorted(d.items(), key=lambda kv: -kv[1][0])]
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    tot = [sum(v[i] for v in by_ext.values()) for i in range(6)]
    summ = {'updated': ts, 'archives_counted': len(G['done']), 'max_nested_depth': max([a['max_depth'] for a in G['arch'].values()] or [0]),
            'distinct_extensions': len(by_ext), 'unique_rule': 'distinct sha256 content per file type across the whole disk',
            'totals': {'files': tot[0], 'bytes': tot[1], 'unique_files_by_type_sum': tot[2], 'unique_bytes_by_type_sum': tot[3],
                       'in_disk12_files': tot[4], 'in_disk12_unique': tot[5]},
            'by_category': fmt(by_cat), 'by_extension': fmt(by_ext),
            'verify': dict(collections.Counter(a['verify'] for a in G['arch'].values())),
            'verify_rule': 'top-level files extracted per archive vs the drive report (7-Zip header listing of each archive)'}
    s3.put_object(Bucket=B, Key=f'{Z4}/_state/stats/ext_summary.json', Body=json.dumps(summ).encode(), ContentType='application/json')
    archives = sorted(G['arch'].values(), key=lambda a: a['finished'] or '', reverse=True)
    s3.put_object(Bucket=B, Key=f'{Z4}/_state/stats/archives.json', Body=json.dumps({'updated': ts, 'archives': archives}).encode(), ContentType='application/json')
    return len(G['done'])


def z2_round():
    out = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    for name, path, col in (('source', '/work/out/json/source_sha256.tsv', 1), ('sharedcontent', '/work/out/json/sharedcontent_files.tsv', 1)):
        if not os.path.exists(path):
            continue
        by = collections.defaultdict(lambda: [0, 0, set(), 0])
        for line in open(path, errors='replace'):
            p = line.rstrip('\n').split('\t')
            if len(p) < 2:
                continue
            rel = p[col]
            size = int(p[0]) if name == 'sharedcontent' else (os.path.getsize('/work/in/src/' + rel) if os.path.exists('/work/in/src/' + rel) else 0)
            x = by[ext_of(rel)]
            x[0] += 1; x[1] += size
            if name == 'source' and p[0] not in x[2]:
                x[2].add(p[0]); x[3] += size
        out[name] = [{'type': k, 'category': cat_of(k), 'files': v[0], 'bytes': v[1],
                      **({'stored_files': len(v[2]), 'stored_bytes': v[3]} if name == 'source' else {})}
                     for k, v in sorted(by.items(), key=lambda kv: -kv[1][0])]
    s3.put_object(Bucket=B, Key=f'{Z2}/_state/stats/ext_summary.json', Body=json.dumps(out).encode(), ContentType='application/json')


if __name__ == '__main__':
    while True:
        t0 = time.time()
        try:
            n = z4_round()
            z2_round()
            print(time.strftime('%H:%M:%S'), 'z4 archives counted', n, 'in', round(time.time() - t0, 1), 's', flush=True)
        except Exception as e:
            print(time.strftime('%H:%M:%S'), 'error', repr(e)[:300], flush=True)
        time.sleep(max(5, 60 - (time.time() - t0)))
__EOF__
setsid nohup python3 /work/stats_agg.py > /work/stats_agg.out 2>&1 < /dev/null &
sleep 90; tail -2 /work/stats_agg.out
