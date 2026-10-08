"""stats_agg.py - in-region aggregation of extraction statistics (runs on an in-region box with the instance role).

Z4: reads every per-archive manifest (_state/manifests/<id>.jsonl.gz, cached locally) + result, and writes
  _state/stats/ext_summary.json   (by extension / category: files, bytes, stored files/bytes; max nesting depth)
  _state/stats/archives.json      (per archive: path, size, files, stored, top types, status) - PRIVATE (has names)
Z2: file types of the source drawing set and of the unpacked SharedContent -> zenitude-data-2/_state/stats/ext_summary.json
Z3 (Zenitude-data-3): see z3_round(). Every manifest row (archive members at every nesting level + loose source files) is
  reduced once to a compact numpy summary on local disk, so a 60 s loop only downloads manifests it has not seen. Writes
  s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/stats/
    ext_summary.json   raw / unique (distinct sha256) / new (not stored by Disk-1, Disk-2 or Z4) per extension and category,
                       loose-file breakdown, nesting, flags, completeness per archive vs the drive report
    pdf_classes.json   CAD / non-CAD / unknown PDFs (the worker's classification), raw / unique / new, with bytes
    progress.json      jobs, archives, bytes and loose files done / total, rate, ETA, result totals
    archives.json      per archive - PRIVATE (has names)
    final_verify.json  once every job in jobs.json has a result

Run:  python3 stats_agg.py                     # Z4 + Z2 every 60 s (unchanged default)
      python3 stats_agg.py --z3 --loop 60      # Z3 only, every 60 s     (--once: a single round)
Z3 needs numpy (pip3 install numpy; orjson optional, faster). Env: STATS_CACHE (default /work/stats_cache),
Z3_PARSE_PROCS (manifest parser processes; 1 = in-process).
"""
import gzip, json, os, time, collections
from concurrent.futures import ThreadPoolExecutor
import boto3

# One bucket constant per section. Z4 is being moved to bim-proprietary-data with identical keys: switch Z4_B there.
Z4_B = 'annotationprod'
Z2_B = 'annotationprod'
Z4 = 'cad-disk-extract/zentitude-data-4'
Z2 = 'cad-disk-extract/zenitude-data-2'
CACHE = os.environ.get('STATS_CACHE', '/work/stats_cache')
os.makedirs(CACHE, exist_ok=True)
from botocore.config import Config as _Cfg
s3 = boto3.client('s3', region_name='ap-south-1', config=_Cfg(retries={'max_attempts': 20, 'mode': 'standard'}))

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


def list_keys(prefix, bucket=Z4_B):
    out, tok = [], None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
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
        IDX.frombytes(s3.get_object(Bucket=Z4_B, Key=f'{Z4}/_control/disk12_sha64.bin')['Body'].read())
    i = _bisect.bisect_left(IDX, h)
    return i < len(IDX) and IDX[i] == h


def load_manifest(jid):
    """Compact per-archive data cached on local disk: ([(ext, size, sha64)], top_level_file_count)."""
    cf = f'{CACHE}/{jid}.v3.pkl'
    if os.path.exists(cf):
        return pickle.load(open(cf, 'rb'))
    body = gzip.decompress(s3.get_object(Bucket=Z4_B, Key=f'{Z4}/_state/manifests/{jid}.jsonl.gz')['Body'].read())
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
        results = list(ex.map(lambda j: json.loads(s3.get_object(Bucket=Z4_B, Key=res[j]['Key'])['Body'].read()), new_ids))
    rep = G.setdefault('report', json.loads(s3.get_object(Bucket=Z4_B, Key=f'{Z4}/_control/report_archives.json')['Body'].read()))
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
    s3.put_object(Bucket=Z4_B, Key=f'{Z4}/_state/stats/ext_summary.json', Body=json.dumps(summ).encode(), ContentType='application/json')
    archives = sorted(G['arch'].values(), key=lambda a: a['finished'] or '', reverse=True)
    s3.put_object(Bucket=Z4_B, Key=f'{Z4}/_state/stats/archives.json', Body=json.dumps({'updated': ts, 'archives': archives}).encode(), ContentType='application/json')
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
    s3.put_object(Bucket=Z2_B, Key=f'{Z2}/_state/stats/ext_summary.json', Body=json.dumps(out).encode(), ContentType='application/json')


# =====================================================================================================================
# Z3: Zenitude-data-3
# =====================================================================================================================
import calendar, glob, hashlib, traceback
from array import array as _arr
from botocore.config import Config as _Config
from botocore.exceptions import ClientError as _ClientError
try:
    import numpy as np
except ImportError:          # only Z3 needs numpy
    np = None
try:
    import orjson as _orjson
    _loads = _orjson.loads
except ImportError:
    _loads = json.loads

Z3_B = os.environ.get('Z3_BUCKET', 'bim-proprietary-data')          # extracted files, manifests, results, heartbeats, stats
Z3 = os.environ.get('Z3_ROOT', 'cad-disk-extract/zenitude-data-3')
Z3_CTL_B = os.environ.get('Z3_CTL_BUCKET', 'annotationprod')        # operator-written control files: jobs.json, report_archives.json
Z3_CTL = os.environ.get('Z3_CTL_PREFIX', 'cad-disk-extract/_control/move/z3')
Z3_STRIP = 'Zenitude-data-3/'
Z3_CACHE = os.path.join(CACHE, 'z3')
Z3_PRIOR = ('prior', 'disk12')                 # dedup labels = content Disk-1, Disk-2 or Z4 already stored (old); the rest is new
Z3_PDF = ('cad', 'document', 'unknown', 'pending')   # pending = PDF row without a worker classification
Z3_DEDUP = ('stored', 'disk', 'archive', 'prior', 'source', 'other')
Z3_PROCS = int(os.environ.get('Z3_PARSE_PROCS', str(max(1, min(8, (os.cpu_count() or 2) - 1)))))
Z3_BATCH = 20_000_000                          # distinct rows merged per step (bounds memory while catching up)
Z3_RATE_WINDOW = 1800                          # ETA: source bytes finished in the last 30 min ...
Z3_ETA_MIN = 0.15                              # ... shown once 15% of the bytes are done (early finishers are small archives)
Z3_RESULT_KEEP = ('id', 'type', 'status', 'size', 'files', 'bytes', 'stored_files', 'stored_bytes', 'dedup_files', 'dedup_bytes',
                  'already_in_disk12_files', 'already_in_disk12_bytes', 'nested_count', 'encrypted_nested', 'ransomware_files',
                  'zero_byte_files', 'upload_error_count', 'source_files', 'long_name_files', 'top_level_encrypted', 'extract_rc',
                  'started', 'finished', 'source')
_Z3S = {}


def _z3_client():
    if 'c' not in _Z3S:            # own client per process (the parser runs in spawned worker processes)
        _Z3S['c'] = boto3.client('s3', region_name='ap-south-1',
                                 config=_Config(max_pool_connections=64, retries={'max_attempts': 20, 'mode': 'standard'}))
    return _Z3S['c']


def _z3_now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _z3_ts(s):
    try:
        return calendar.timegm(time.strptime(s, '%Y-%m-%dT%H:%M:%SZ'))
    except Exception:
        return None


def _z3_put(key, obj):
    _z3_client().put_object(Bucket=Z3_B, Key=f'{Z3}/_state/stats/{key}', Body=json.dumps(obj, separators=(',', ':')).encode(),
                            ContentType='application/json')


_z3_jc = {}


def z3_get_json(bucket, key, transform=None):
    """JSON object (optionally reduced by `transform`), downloaded again only when its ETag changed. None if it does not exist."""
    old = _z3_jc.get((bucket, key))
    try:
        r = _z3_client().get_object(Bucket=bucket, Key=key, **({'IfNoneMatch': old[0]} if old else {}))
    except _ClientError as e:
        code = str(e.response.get('Error', {}).get('Code'))
        if code in ('304', 'NotModified') and old:
            return old[1]
        if code in ('NoSuchKey', '404', 'NotFound'):
            _z3_jc.pop((bucket, key), None)
            return None
        raise
    obj = json.loads(r['Body'].read())
    if transform:
        obj = transform(obj)
    _z3_jc[(bucket, key)] = (r['ETag'], obj)
    return obj


def _z3_jobs_compact(jobs):
    """jobs.json (archive jobs {id,key,size}; loose jobs {id,type:'loose',dir,size,files} or {..,keys:[[key,size],...]})
    -> {id: compact job}."""
    out = {}
    for j in jobs or []:
        if j.get('type') == 'loose':
            ks = j.get('keys') or []
            out[j['id']] = {'id': j['id'], 'loose': True, 'bytes': j.get('size') or sum(k[1] or 0 for k in ks),
                            'files': j['files'] if j.get('files') is not None else len(ks)}
        else:
            out[j['id']] = {'id': j['id'], 'loose': False, 'bytes': j.get('size') or 0, 'key': j.get('key', '')}
    return out


def _z3_exthash(name):
    return int.from_bytes(hashlib.blake2b(name.encode('utf-8', 'surrogatepass'), digest_size=8).digest(), 'little')


def _z3_pdfcls(v):
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    return 3 if v is None else {'cad': 0, 'document': 1, 'unknown': 2}.get(v, 2)


def z3_parse_manifest(jid, etag, loose_job=None):
    """Download one manifest and reduce it to <cache>/m/<jid>.<etag>.v1.npz (returns the path). Per extension: raw files, bytes,
    prior files, prior bytes; the distinct (extension, sha64) pairs with size and prior flag; the same for PDFs by class; and
    meta = rows, top-level files (not inside a nested archive), zero-byte / ransomware rows, loose flag, dedup kinds."""
    cf = _z3_cf(jid, etag)
    if os.path.exists(cf):
        return cf
    os.makedirs(os.path.join(Z3_CACHE, 'm'), exist_ok=True)
    os.makedirs(os.path.join(Z3_CACHE, 'tmp'), exist_ok=True)
    tmp = os.path.join(Z3_CACHE, 'tmp', f'{jid}.{os.getpid()}.jsonl.gz')
    _z3_client().download_file(Z3_B, f'{Z3}/_state/manifests/{jid}.jsonl.gz', tmp)
    names, nid, ecache = [], {}, {}
    ex, sh, sz, pr = _arr('I'), _arr('Q'), _arr('q'), bytearray()
    pc, psh, psz, ppr = bytearray(), _arr('Q'), _arr('q'), bytearray()
    dd = dict.fromkeys(Z3_DEDUP, 0)
    rows = top = zero = ransom = loose_rows = 0
    sds_roots = {}                                      # SDS2 job root -> (jsetup sha64, prior flag)
    mark = NESTED_MARK.search
    try:
        with gzip.open(tmp, 'rb') as fh:
            for line in fh:
                if len(line) < 3:
                    continue
                e = _loads(line)
                p = e['path']
                base = p[p.rfind('/') + 1:]
                d = base.rfind('.')
                raw_e = base[d + 1:] if d >= 0 else None
                li = ecache.get(raw_e)
                if li is None:
                    nm = ext_of('a.' + raw_e) if raw_e is not None else '(none)'
                    li = nid.get(nm)
                    if li is None:
                        li = nid[nm] = len(names)
                        names.append(nm)
                    ecache[raw_e] = li
                size = e.get('size') or 0
                h = int(e['sha256'][:16], 16)
                dk = e.get('dedup')
                old = dk in Z3_PRIOR
                ex.append(li); sh.append(h); sz.append(size); pr.append(old)
                rows += 1
                dd['stored' if dk is None else 'prior' if old else dk if dk in dd else 'other'] += 1
                if e.get('loose'):
                    loose_rows += 1
                elif '!/' not in p or not mark(p):
                    top += 1
                fl = e.get('flags')
                if fl:
                    if 'zero_bytes' in fl:
                        zero += 1
                    if 'ransomware_encrypted' in fl:
                        ransom += 1
                if names[li] == 'pdf':
                    pc.append(_z3_pdfcls(e.get('pdf_class'))); psh.append(h); psz.append(size); ppr.append(old)
                lb = base.lower()
                if lb in ('jsetup', 'mem_idx'):
                    parent = p[:p.rfind('/') + 1] if '/' in p else ''
                    pl = parent.lower()
                    if (lb == 'jsetup' and pl.endswith('main/')) or (lb == 'mem_idx' and pl.endswith('mem/')):
                        root = parent[:-len('main/')] if lb == 'jsetup' else parent[:-len('mem/')]
                        if lb == 'jsetup' or root not in sds_roots:
                            sds_roots[root] = (h, old)
        sds = [0, 0, 0]                                     # files, bytes, prior files inside SDS2 job folders
        if sds_roots:
            roots = set(sds_roots)
            whole = '' in roots
            with gzip.open(tmp, 'rb') as fh:
                for line in fh:
                    if len(line) < 3:
                        continue
                    e = _loads(line)
                    p = e['path']
                    inside = whole
                    if not inside:
                        i = p.find('/')
                        while i >= 0:
                            if p[:i + 1] in roots:
                                inside = True
                                break
                            i = p.find('/', i + 1)
                    if inside:
                        sds[0] += 1; sds[1] += e.get('size') or 0; sds[2] += e.get('dedup') in Z3_PRIOR
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    loose = bool(loose_job) if loose_job is not None else (rows > 0 and loose_rows == rows)
    arrs = {}
    arrs.update(_z3_reduce('', np.frombuffer(ex, np.uint32), sh, sz, pr, names))
    arrs.update(_z3_reduce('p', np.frombuffer(pc, np.uint8), psh, psz, ppr, ['pdfclass:' + x for x in Z3_PDF]))
    blob = '\n'.join(names).encode('utf-8', 'surrogatepass')
    meta = np.array([rows, top, zero, ransom, int(loose), int(arrs['raw'][:, 1].sum())] + [dd[k] for k in Z3_DEDUP], np.int64)
    tmpcf = cf[:-4] + f'.{os.getpid()}.tmp.npz'
    sj = list(sds_roots.values())
    np.savez(tmpcf, names=np.frombuffer(blob, np.uint8) if blob else np.zeros(0, np.uint8), meta=meta,
             sds2=np.array([len(sj)] + sds, np.int64), sds2_ids=np.array([x[0] for x in sj], np.uint64),
             sds2_prior=np.array([int(x[1]) for x in sj], np.uint8), **arrs)
    os.replace(tmpcf, cf)
    for old in glob.glob(os.path.join(Z3_CACHE, 'm', f'{jid}.*.v*.npz')):   # older copies / older cache versions
        if old != cf:
            try:
                os.remove(old)
            except OSError:
                pass
    return cf


def _z3_reduce(pfx, idx, sha, size, prior, hash_names):
    """Per-row arrays -> raw[name] = (files, bytes, prior files, prior bytes) and the distinct (name, sha64) pairs
    (key = sha64 XOR hash(name), so the sha64 is recoverable) with their size and prior flag."""
    n = len(hash_names)
    i = idx.astype(np.int64)
    h = np.frombuffer(sha, np.uint64)
    s = np.frombuffer(size, np.int64)
    o = np.frombuffer(prior, np.uint8).astype(bool)
    raw = np.zeros((n, 4), np.int64)
    if len(i):
        raw[:, 0] = np.bincount(i, minlength=n)
        raw[:, 1] = np.bincount(i, weights=s, minlength=n).astype(np.int64)
        raw[:, 2] = np.bincount(i[o], minlength=n)
        raw[:, 3] = np.bincount(i[o], weights=s[o], minlength=n).astype(np.int64)
    hx = np.array([_z3_exthash(x) for x in hash_names], np.uint64)
    key = h ^ hx[i] if len(i) else np.zeros(0, np.uint64)
    uk, first = np.unique(key, return_index=True)
    return {pfx + 'raw': raw, pfx + 'uk': uk, pfx + 'ue': i[first].astype(np.uint32), pfx + 'us': s[first], pfx + 'up': o[first]}


def _z3_cf(jid, etag):
    return os.path.join(Z3_CACHE, 'm', f"{jid}.{etag.strip(chr(34))}.v2.npz")


def _z3_parse_task(args):
    try:
        return z3_parse_manifest(*args)
    except Exception as e:                  # one bad / throttled manifest must not stop the round; retried next round
        return 'error: ' + repr(e)[:200]


def _z3_list(bucket, prefix):
    out, tok = [], None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix)
        if tok:
            kw['ContinuationToken'] = tok
        r = _z3_client().list_objects_v2(**kw)
        out += r.get('Contents', [])
        if not r.get('IsTruncated'):
            return out
        tok = r['NextContinuationToken']


class _Distinct:
    """Sorted numpy uint64 set; add(sorted unique keys) inserts the unseen ones and returns their mask."""

    def __init__(self):
        self.k = np.zeros(0, np.uint64)

    def add(self, keys):
        if not len(keys):
            return np.zeros(0, bool)
        pos = np.searchsorted(self.k, keys)
        hit = np.zeros(len(keys), bool)
        m = pos < len(self.k)
        hit[m] = self.k[pos[m]] == keys[m]
        new = ~hit
        if new.any():
            self.k = np.insert(self.k, pos[new], keys[new])
        return new


class _Tally:
    """Per name (extension, or PDF class): raw = every row, unique = distinct (name, sha64) pairs, prior = content an earlier
    disk already stored, new = raw/unique minus prior. `distinct` counts each sha64 once across all names."""

    def __init__(self, fixed_hash=None):
        self.ids, self.names = {}, []
        self.hx = np.zeros(0, np.uint64)
        self.raw = np.zeros((0, 4), np.int64)      # files, bytes, prior files, prior bytes
        self.uni = np.zeros((0, 4), np.int64)      # unique files, unique bytes, prior unique, prior unique bytes
        self.pairs, self.shas = _Distinct(), _Distinct()
        self.distinct = np.zeros(4, np.int64)
        self.fixed_hash = fixed_hash

    def gids(self, names):
        out = []
        for nm in names:
            i = self.ids.get(nm)
            if i is None:
                i = self.ids[nm] = len(self.names)
                self.names.append(nm)
            out.append(i)
        grow = len(self.names) - len(self.raw)
        if grow > 0:
            self.raw = np.vstack([self.raw, np.zeros((grow, 4), np.int64)])
            self.uni = np.vstack([self.uni, np.zeros((grow, 4), np.int64)])
            new = self.names[len(self.hx):]
            self.hx = np.concatenate([self.hx, np.array([self.fixed_hash(x) if self.fixed_hash else _z3_exthash(x) for x in new], np.uint64)])
        return np.array(out, np.int64)

    def add(self, parts):
        """parts: [(names, raw[len(names),4], uk, ue (index into names), us, up)]; pairs distinct within each part."""
        K, E, S, P = [], [], [], []
        for names, raw, uk, ue, us, up in parts:
            if not len(names):
                continue
            g = self.gids(names)
            self.raw[g] += raw
            if len(uk):
                K.append(uk); E.append(g[ue.astype(np.int64)]); S.append(us); P.append(up)
        if not K:
            return
        key, e, s, p = np.concatenate(K), np.concatenate(E), np.concatenate(S), np.concatenate(P)
        uk, first = np.unique(key, return_index=True)
        e, s, p = e[first], s[first], p[first]
        new = self.pairs.add(uk)
        if not new.any():
            return
        uk, e, s, p = uk[new], e[new], s[new], p[new]
        n = len(self.names)
        self.uni[:, 0] += np.bincount(e, minlength=n)
        self.uni[:, 1] += np.bincount(e, weights=s, minlength=n).astype(np.int64)   # float64 sums are exact below 2**53
        self.uni[:, 2] += np.bincount(e[p], minlength=n)
        self.uni[:, 3] += np.bincount(e[p], weights=s[p], minlength=n).astype(np.int64)
        sha = uk ^ self.hx[e]                       # a sha64 not seen before can only arrive with a pair not seen before
        us, f2 = np.unique(sha, return_index=True)
        nw = self.shas.add(us)
        s2, p2 = s[f2][nw], p[f2][nw]
        self.distinct += np.array([len(s2), int(s2.sum()), int(p2.sum()), int(s2[p2].sum())], np.int64)

    def row(self, i):
        f, b, pf, pb = (int(x) for x in self.raw[i])
        uf, ub, pu, pub = (int(x) for x in self.uni[i])
        return {'type': self.names[i], 'files': f, 'bytes': b, 'unique_files': uf, 'unique_bytes': ub, 'prior_files': pf,
                'prior_unique': pu, 'new_files': f - pf, 'new_unique': uf - pu, 'new_unique_bytes': ub - pub}

    def rows(self):
        return sorted((self.row(i) for i in range(len(self.names))), key=lambda r: -r['files'])

    def totals(self):
        f, b, pf, pb = (int(x) for x in self.raw.sum(axis=0)) if len(self.raw) else (0, 0, 0, 0)
        uf, ub, pu, pub = (int(x) for x in self.distinct)
        return {'files': f, 'bytes': b, 'unique_files': uf, 'unique_bytes': ub, 'prior_files': pf, 'prior_bytes': pb,
                'prior_unique': pu, 'new_files': f - pf, 'new_bytes': b - pb, 'new_unique': uf - pu, 'new_unique_bytes': ub - pub,
                'unique_files_by_type_sum': int(self.uni[:, 0].sum()) if len(self.uni) else 0}


def _z3_state():
    return {'done': {}, 'arch': {}, 'rows': 0, 'top': 0, 'zero': 0, 'ransom': 0, 'dedup': dict.fromkeys(Z3_DEDUP, 0),
            'all': _Tally(), 'loose': _Tally(), 'pdf': _Tally(lambda x: _z3_exthash('pdfclass:' + x)),
            'pdf_loose': _Tally(lambda x: _z3_exthash('pdfclass:' + x)),
            'sds2': [0, 0, 0, 0], 'sds2_ids': {}}


def _z3_load_cache(cf, args=None):
    try:
        z = np.load(cf)
        z['meta']
    except Exception:              # unreadable cache file: parse the manifest again
        if not args:
            raise
        try:
            os.remove(cf)
        except OSError:
            pass
        z = np.load(z3_parse_manifest(*args))
    blob = z['names'].tobytes()
    names = blob.decode('utf-8', 'surrogatepass').split('\n') if blob else []
    sd = (z['sds2'], z['sds2_ids'], z['sds2_prior']) if 'sds2' in z.files else (np.zeros(4, np.int64), np.zeros(0, np.uint64), np.zeros(0, np.uint8))
    return {'names': names, 'meta': z['meta'], 'sds2': sd, 'part': (names, z['raw'], z['uk'], z['ue'], z['us'], z['up']),
            'pdf': (list(Z3_PDF), z['praw'], z['puk'], z['pue'], z['pus'], z['pup'])}


def _z3_add_batch(G, items):
    """items: [(jid, etag, cache dict)] -> tallies, per-archive records; marks each job counted."""
    if not items:
        return
    G['all'].add([c['part'] for _, _, c in items])
    G['loose'].add([c['part'] for _, _, c in items if c['meta'][4]])
    G['pdf'].add([c['pdf'] for _, _, c in items])
    G['pdf_loose'].add([c['pdf'] for _, _, c in items if c['meta'][4]])
    for jid, etag, c in items:
        G['done'][jid] = etag
        sv, sid, spr = c['sds2']
        for k in range(4):
            G['sds2'][k] += int(sv[k])
        for h, pr_ in zip(sid.tolist(), spr.tolist()):
            G['sds2_ids'][h] = G['sds2_ids'].get(h, 0) or pr_
        m = [int(x) for x in c['meta']]
        G['rows'] += m[0]; G['zero'] += m[2]; G['ransom'] += m[3]
        for k, v in zip(Z3_DEDUP, m[6:]):
            G['dedup'][k] += v
        raw = c['part'][1]
        order = np.argsort(-raw[:, 0])[:6] if len(raw) else []
        G['arch'][jid] = {'rows': m[0], 'top': m[1], 'loose': bool(m[4]), 'zero': m[2], 'ransom': m[3],
                          'top_types': [[c['names'][i], int(raw[i, 0])] for i in order]}
        if not m[4]:
            G['top'] += m[1]


def _z3_result_summary(r):
    nested = r.get('nested') or []
    depth = collections.Counter(int(x.get('depth') or 0) for x in nested)
    s = {k: r.get(k) for k in Z3_RESULT_KEEP if k in r}
    s.update(max_depth=max(depth) if depth else 0, depth={str(k): v for k, v in depth.items()},
             nested_errors=len(r.get('nested_errors') or []))
    return s


def _z3_pool():
    if 'pool' not in _Z3S:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        _Z3S['pool'] = ProcessPoolExecutor(Z3_PROCS, mp_context=mp.get_context('spawn'))
    return _Z3S['pool']


def _z3_progress(jobs, res):
    """jobs: {id: compact job}; res: {id: result summary} (only ids in jobs). Bytes = archive size / loose file sizes."""
    arch = [j for j in jobs.values() if not j['loose']]
    loose = [j for j in jobs.values() if j['loose']]
    done = lambda js: [j for j in js if j['id'] in res]
    p = {'jobs_total': len(jobs), 'jobs_done': len(res),
         'archive_jobs_total': len(arch), 'archive_jobs_done': len(done(arch)),
         'archive_bytes_total': sum(j['bytes'] for j in arch), 'archive_bytes_done': sum(j['bytes'] for j in done(arch)),
         'loose_jobs_total': len(loose), 'loose_jobs_done': len(done(loose)),
         # loose totals: a finished folder job reports what it actually listed (source_files / bytes); the job-list estimate from
         # the drive report counts sub-folders recursively, so it is only used for folders not yet processed
         'loose_files_total': sum(res[j['id']].get('source_files') if j['id'] in res and res[j['id']].get('source_files') is not None
                                  else j['files'] for j in loose),
         'loose_files_done': sum(res[j['id']].get('files') or 0 for j in done(loose)),
         'loose_bytes_total': sum((res[j['id']].get('bytes') or 0) if j['id'] in res else j['bytes'] for j in loose),
         'loose_bytes_done': sum(res[j['id']].get('bytes') or 0 for j in done(loose))}
    p['bytes_total'] = p['archive_bytes_total'] + p['loose_bytes_total']
    p['bytes_done'] = p['archive_bytes_done'] + p['loose_bytes_done']
    now = time.time()
    recent = [(jobs.get(i) or {}).get('bytes', r.get('size') or 0) for i, r in res.items()
              if (_z3_ts(r.get('finished')) or 0) > now - Z3_RATE_WINDOW]
    rate = sum(recent) / Z3_RATE_WINDOW if recent else 0
    frac = p['bytes_done'] / p['bytes_total'] if p['bytes_total'] else 0
    p.update(rate_bytes_per_s=rate, rate_window_s=Z3_RATE_WINDOW, jobs_finished_in_window=len(recent),
             eta_s=(p['bytes_total'] - p['bytes_done']) / rate if rate and frac >= Z3_ETA_MIN and frac < 1 else (0 if frac >= 1 else None),
             eta_rule=f'remaining source bytes / bytes finished in the last {Z3_RATE_WINDOW // 60} min; shown once {int(Z3_ETA_MIN * 100)}% is done',
             status=dict(collections.Counter(r.get('status') for r in res.values())),
             complete=bool(jobs) and len(res) >= len(jobs))
    return p


def z3_round():
    """One incremental Z3 aggregation round (see the module docstring); returns (jobs counted, manifest rows counted).
    State lives in memory; per-manifest summaries and result summaries are cached under STATS_CACHE/z3, so a restart
    recounts from local disk instead of S3."""
    if np is None:
        raise RuntimeError('Z3 aggregation needs numpy: pip3 install numpy')
    c = _z3_client()
    os.makedirs(os.path.join(Z3_CACHE, 'm'), exist_ok=True)
    G = _Z3S.get('G')
    if G is None:
        G = _Z3S['G'] = _z3_state()
    jobs = z3_get_json(Z3_CTL_B, f'{Z3_CTL}/jobs.json', _z3_jobs_compact) or {}
    rep = z3_get_json(Z3_CTL_B, f'{Z3_CTL}/report_archives.json') or {}
    res_objs = {o['Key'].rsplit('/', 1)[-1][:-5]: o for o in _z3_list(Z3_B, f'{Z3}/_state/results/') if o['Key'].endswith('.json')}
    mans = {o['Key'].rsplit('/', 1)[-1].split('.')[0]: o['ETag'] for o in _z3_list(Z3_B, f'{Z3}/_state/manifests/')
            if o['Key'].endswith('.jsonl.gz')}
    if jobs:                                               # count only jobs of the current job list
        res_objs = {j: o for j, o in res_objs.items() if j in jobs}
    # results: small summaries, re-read only when the ETag changes (kept on disk across restarts)
    rc_path = os.path.join(Z3_CACHE, 'results.json')
    if 'res' not in _Z3S:
        try:
            _Z3S['res'] = json.load(open(rc_path))
        except Exception:
            _Z3S['res'] = {}
    rcache = _Z3S['res']
    todo = [j for j, o in res_objs.items() if (rcache.get(j) or [None])[0] != o['ETag']]
    if todo:
        def one(j):
            try:
                return j, res_objs[j]['ETag'], _z3_result_summary(json.loads(c.get_object(Bucket=Z3_B, Key=res_objs[j]['Key'])['Body'].read()))
            except Exception:
                return j, None, None
        with ThreadPoolExecutor(32) as tp:
            for j, et, s in tp.map(one, todo):
                if s is not None:
                    rcache[j] = [et, s]
        json.dump(rcache, open(rc_path + '.tmp', 'w'))
        os.replace(rc_path + '.tmp', rc_path)
    res = {j: rcache[j][1] for j in res_objs if j in rcache}
    # a counted manifest was rewritten / removed, or its result is gone -> recount everything from the local caches
    if any(mans.get(j) != et or j not in res for j, et in G['done'].items()):
        G = _Z3S['G'] = _z3_state()
    new_ids = [j for j in res if j in mans and j not in G['done']]
    args = {j: (j, mans[j], jobs[j]['loose'] if j in jobs else None) for j in new_ids}
    missing = [a for a in args.values() if not os.path.exists(_z3_cf(a[0], a[1]))]
    if len(missing) > 1 and Z3_PROCS > 1:            # download + parse new manifests in parallel processes
        from concurrent.futures.process import BrokenProcessPool
        try:
            list(_z3_pool().map(_z3_parse_task, missing))
        except BrokenProcessPool:
            _Z3S.pop('pool').shutdown(wait=False)
            raise
    batch, rows = [], 0
    for j in new_ids:
        a = args[j]
        cf = _z3_cf(a[0], a[1])
        try:
            cd = _z3_load_cache(cf if os.path.exists(cf) else z3_parse_manifest(*a), a)
        except Exception as e:
            print(time.strftime('%H:%M:%S'), 'z3 manifest', j, 'skipped this round:', repr(e)[:200], flush=True)
            continue
        batch.append((j, mans[j], cd)); rows += len(cd['part'][2])
        if rows >= Z3_BATCH:
            _z3_add_batch(G, batch); batch, rows = [], 0
    _z3_add_batch(G, batch)
    # ---- outputs ----
    ts = _z3_now()
    counted = {j: res[j] for j in G['done'] if j in res}
    for j, r in counted.items():                           # per-archive record + completeness vs the drive report
        a = G['arch'][j]
        jb = jobs.get(j) or {}
        if a['loose']:
            a.update(verify='loose', path=None)
            continue
        src = jb.get('key') or (r.get('source') or '').split('/', 3)[-1]
        rel = src[len(Z3_STRIP):] if src.startswith(Z3_STRIP) else src
        rr = rep.get(rel) or rep.get(src)
        a.update(path=rel, report_files=rr.get('files') if rr else None, report_status=rr.get('status') if rr else None,
                 verify=('no_report_entry' if not rr else 'match' if rr.get('files') == a['top'] else
                         'more_than_report' if a['top'] > (rr.get('files') or 0) else 'fewer_than_report'))
    arch_recs = [(j, G['arch'][j]) for j in counted if not G['arch'][j]['loose']]
    verify = dict(collections.Counter(a['verify'] for _, a in arch_recs))
    incomplete_listing = collections.Counter(a['verify'] for _, a in arch_recs if a.get('report_status') not in (None, 'listed'))
    depth = collections.Counter()
    for r in counted.values():
        depth.update({int(k): v for k, v in (r.get('depth') or {}).items()})
    rt = lambda k: sum(r.get(k) or 0 for r in res.values())
    T, L = G['all'], G['loose']
    by_ext = T.rows()
    by_cat = collections.defaultdict(lambda: collections.Counter())
    for t in by_ext:
        by_cat[cat_of(t['type'])].update({k: v for k, v in t.items() if k != 'type'})
    fmt_cat = lambda d: sorted(({'type': k, **dict(v)} for k, v in d.items()), key=lambda r: -r['files'])
    l_ext = L.rows()
    l_cat = collections.defaultdict(lambda: collections.Counter())
    for t in l_ext:
        l_cat[cat_of(t['type'])].update({k: v for k, v in t.items() if k != 'type'})
    n_arch = sum(1 for j in counted if not G['arch'][j]['loose'])
    summ = {'updated': ts, 'jobs_counted': len(counted), 'archive_jobs_counted': n_arch, 'loose_jobs_counted': len(counted) - n_arch,
            'rows_counted': G['rows'], 'distinct_extensions': len(by_ext),
            'max_nested_depth': max(depth) if depth else 0,
            'unique_rule': 'unique = distinct sha256 content per file type across the whole disk (archive members at every nesting level + loose files); totals.unique_files counts each content once across all types',
            'new_rule': 'new = content whose sha256 is not in the Disk-1 / Disk-2 / Z4 index (rows the worker recorded as dedup "prior" are old)',
            'totals': dict(T.totals(), zero_byte_files=G['zero'], ransomware_files=G['ransom'], dedup_kinds=dict(G['dedup'])),
            'archive_members': {'files': G['rows'] - L.totals()['files'], 'top_level_files': G['top']},
            'loose': L.totals(),
            'by_category': fmt_cat(by_cat), 'by_extension': by_ext,
            'loose_by_category': fmt_cat(l_cat), 'loose_by_extension': l_ext,
            'nested': {'unpacked': sum(r.get('nested_count') or 0 for r in counted.values()),
                       'encrypted_blocked': sum(r.get('encrypted_nested') or 0 for r in counted.values()),
                       'top_level_encrypted': sum(1 for r in counted.values() if r.get('top_level_encrypted')),
                       'nested_errors': sum(r.get('nested_errors') or 0 for r in counted.values()),
                       'max_depth': max(depth) if depth else 0, 'by_depth': {str(k): depth[k] for k in sorted(depth)}},
            'verify': verify, 'verify_report_listing_incomplete': dict(incomplete_listing),
            'verify_files': {'extracted_top_level': sum(a['top'] for _, a in arch_recs),
                             'report_files': sum(a.get('report_files') or 0 for _, a in arch_recs)},
            'report_loaded': bool(rep),
            'verify_rule': 'top-level files extracted per archive (not inside a nested archive) vs the drive report (7-Zip header listing of each archive)'}
    sj = G['sds2']; ids = G['sds2_ids']
    summ['sds2'] = {'jobs_raw': sj[0], 'jobs_unique': len(ids), 'jobs_new_unique': sum(1 for v in ids.values() if not v),
                    'files': sj[1], 'bytes': sj[2], 'files_prior': sj[3], 'files_new': sj[1] - sj[3],
                    'rule': 'an SDS2 job = a folder holding main/jsetup (or mem/mem_idx); unique = distinct jsetup content; new = jsetup not stored by Disk-1/2/Z4; files = every file inside job folders'}
    _z3_put('ext_summary.json', summ)

    def pdf_block(P):
        out = {}
        for i, nm in enumerate(P.names):
            r = P.row(i)
            out[nm] = {'raw': r['files'], 'unique': r['unique_files'], 'new_raw': r['new_files'], 'new_unique': r['new_unique'],
                       'raw_bytes': r['bytes'], 'unique_bytes': r['unique_bytes'], 'new_unique_bytes': r['new_unique_bytes']}
        for nm in Z3_PDF:
            out.setdefault(nm, {'raw': 0, 'unique': 0, 'new_raw': 0, 'new_unique': 0, 'raw_bytes': 0, 'unique_bytes': 0, 'new_unique_bytes': 0})
        t = P.totals()
        return {'pdf_paths': t['files'], 'pdf_unique': t['unique_files'], 'pdf_new_unique': t['new_unique'], 'classes': out}
    _z3_put('pdf_classes.json', {'updated': ts, 'jobs_counted': len(counted), **pdf_block(G['pdf']), 'loose': pdf_block(G['pdf_loose']),
                                 'rule': 'cad = CAD/plot producer or page >= A3; document = office/scanner producer or smaller page; unknown = no readable metadata (classified by the extraction worker from the local file)'})
    prog = _z3_progress(jobs, res)
    prog.update(updated=ts, results_totals={k: rt(k) for k in ('files', 'bytes', 'stored_files', 'stored_bytes', 'dedup_files', 'dedup_bytes',
                                                               'already_in_disk12_files', 'already_in_disk12_bytes', 'nested_count',
                                                               'encrypted_nested', 'ransomware_files', 'zero_byte_files', 'upload_error_count')},
                jobs_counted_in_stats=len(counted))
    _z3_put('progress.json', prog)
    arcs = []
    for j, a in arch_recs:
        r = counted[j]
        arcs.append({'id': j, 'path': a.get('path'), 'size': r.get('size'), 'status': r.get('status'), 'files': r.get('files'),
                     'stored_files': r.get('stored_files'), 'top_level_files': a['top'], 'report_files': a.get('report_files'),
                     'report_status': a.get('report_status'), 'verify': a['verify'], 'nested': r.get('nested_count'),
                     'encrypted_nested': r.get('encrypted_nested'), 'max_depth': r.get('max_depth'), 'finished': r.get('finished'),
                     'top_types': a['top_types']})
    arcs.sort(key=lambda a: a['finished'] or '', reverse=True)
    _z3_put('archives.json', {'updated': ts, 'archives': arcs})
    if prog['complete']:
        errs = {o['Key'].rsplit('/', 1)[-1].split('.')[0] for o in _z3_list(Z3_B, f'{Z3}/_state/errors/')}
        lt = L.totals()
        _z3_put('final_verify.json', {
            'checked_at': ts, 'jobs': len(jobs), 'results': len(res), 'archive_jobs': prog['archive_jobs_total'],
            'loose_jobs': prog['loose_jobs_total'], 'status': prog['status'],
            'completeness_vs_drive_report': verify, 'report_listing_incomplete': dict(incomplete_listing),
            'loose_files_listed': prog['loose_files_total'], 'loose_files_hashed': lt['files'],
            'loose_files_missing': max(0, prog['loose_files_total'] - lt['files']),
            'error_records': len(errs), 'error_jobs_still_without_result': sum(1 for j in errs if j not in res),
            'manifest_rows': G['rows'], 'result_files': rt('files'), 'rows_match_results': G['rows'] == rt('files'),
            'jobs_counted_in_stats': len(counted),
            'totals': dict(prog['results_totals'], unique_files=T.totals()['unique_files'], new_unique=T.totals()['new_unique'],
                           new_unique_bytes=T.totals()['new_unique_bytes']),
            'max_nested_depth': summ['max_nested_depth'], 'distinct_extensions': summ['distinct_extensions']})
    return len(counted), G['rows']


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='in-region extraction statistics (default: Z4 + Z2)')
    ap.add_argument('--z4', action='store_true', help='Zentitude-data-4 round')
    ap.add_argument('--z2', action='store_true', help='Zenitude-data-2 round')
    ap.add_argument('--z3', action='store_true', help='Zenitude-data-3 round (incremental; needs numpy)')
    ap.add_argument('--loop', type=int, default=60, help='seconds between rounds (default 60)')
    ap.add_argument('--once', action='store_true', help='run a single round and exit')
    a = ap.parse_args()
    if not (a.z4 or a.z2 or a.z3):
        a.z4 = a.z2 = True
    while True:
        t0 = time.time()
        if a.z4 or a.z2:
            try:
                if a.z4:
                    n = z4_round()
                if a.z2:
                    z2_round()
                print(time.strftime('%H:%M:%S'), 'z4 archives counted', n if a.z4 else '-', 'in', round(time.time() - t0, 1), 's', flush=True)
            except Exception as e:
                print(time.strftime('%H:%M:%S'), 'error', repr(e)[:300], flush=True)
        if a.z3:
            t1 = time.time()
            try:
                nj, nr = z3_round()
                print(time.strftime('%H:%M:%S'), 'z3 jobs counted', nj, 'rows', nr, 'in', round(time.time() - t1, 1), 's', flush=True)
            except Exception:
                print(time.strftime('%H:%M:%S'), 'z3 error', traceback.format_exc()[-1500:], flush=True)
        if a.once:
            break
        time.sleep(max(5, a.loop - (time.time() - t0)))
