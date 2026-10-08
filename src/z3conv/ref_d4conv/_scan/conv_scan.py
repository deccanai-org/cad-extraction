#!/usr/bin/env python3
"""Zentitude-data-4 conversion scan: read every per-archive manifest, collect the 3D model files
(.ifc .ifczip .ifcxml .db1 .stp .step) and every file inside the SDS/2 job folders listed by the
drive report, drop content Disk-1/2 already stored (disk12_sha64.bin), resolve stored keys and write
the job lists under _control/conv/{ifc,db1,sds2}/jobs.json (+ native STEP index).

usage: python3 conv_scan.py [--procs 12] [--dry]   (runs in-region; reads 6.5 GB of manifests)
"""
import os, sys, re, json, gzip, time, array, bisect, hashlib, argparse, collections, zlib
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

B = 'annotationprod'; Z4 = 'cad-disk-extract/zentitude-data-4'; CONV = Z4 + '/_control/conv'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries={'max_attempts': 10, 'mode': 'adaptive'}))
EXT = ('.ifc', '.ifczip', '.ifcxml', '.db1', '.stp', '.step')
PAT = re.compile(rb'\.(?:ifc|ifczip|ifcxml|db1|stp|step)", "size"', re.I)
SDS2 = {}          # archive id -> [path_in_archive prefixes]


def ext_of(p):
    b = p.rsplit('/', 1)[-1]
    return ('.' + b.rsplit('.', 1)[-1].lower()) if '.' in b else ''


_PC = {}


def pclient():
    # one client per worker process: a client inherited through fork shares SSL sockets (WRONG_VERSION_NUMBER)
    if _PC.get('pid') != os.getpid():
        _PC['pid'] = os.getpid(); _PC['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 10, 'mode': 'adaptive'}))
    return _PC['c']


def scan(arg):
    jid, akey, prefixes = arg
    body = None; err = None
    for attempt in range(5):
        try:
            body = gzip.decompress(pclient().get_object(Bucket=B, Key=f'{Z4}/_state/manifests/{jid}.jsonl.gz')['Body'].read()); break
        except Exception as e:
            err = f'{type(e).__name__}: {str(e)[:200]}'; _PC.clear(); time.sleep(2 + attempt * 3)
    if body is None:
        return jid, None, None, err
    models, sds = [], collections.defaultdict(list)
    pre = [(p.rstrip('/') + '/', i) for i, p in enumerate(prefixes)]
    for line in body.splitlines():
        if not line:
            continue
        hit = PAT.search(line)
        if not hit and not pre:
            continue
        e = json.loads(line)
        p = e['path']
        if hit and ext_of(p) in EXT:
            models.append((e['sha256'], e['size'], p, e.get('key'), e.get('dedup')))
        for pr, i in pre:
            if p.startswith(pr):
                sds[i].append((p[len(pr):], e['sha256'], e['size'], e.get('key'), e.get('dedup')))
    return jid, models, dict(sds), None


IDX = array.array('Q')


def in_d12(sha):
    h = int(sha[:16], 16); i = bisect.bisect_left(IDX, h)
    return i < len(IDX) and IDX[i] == h


def marker(sha):
    try:
        return s3.get_object(Bucket=B, Key=f'{Z4}/_state/sha/{sha[:2]}/{sha}')['Body'].read().decode()
    except ClientError:
        return None


def db1_engine(key):
    """Tekla engine banner (first bytes of the gunzipped DB1)"""
    try:
        raw = s3.get_object(Bucket=B, Key=key, Range='bytes=0-65535')['Body'].read()
        data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
        m = re.search(rb'(\d+\.\d+)', data[:16])
        return m.group(1).decode() if m else None, data[:16].hex()
    except Exception as e:
        return None, 'err:%s' % type(e).__name__


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--procs', type=int, default=12); ap.add_argument('--dry', action='store_true')
    ap.add_argument('--out', default='/work/conv4')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True); t0 = time.time()
    jobs = json.loads(s3.get_object(Bucket=B, Key=f'{Z4}/_control/jobs.json')['Body'].read())
    id_of = {j['key'].split('/', 1)[1]: j['id'] for j in jobs}          # archive path (no disk prefix) -> id
    akey = {j['id']: j['key'].split('/', 1)[1] for j in jobs}
    rows = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sds2_report_rows.json')))
    pref = collections.defaultdict(list); rowref = []
    for r in rows:
        jid = id_of.get(r[1])
        rowref.append((jid, len(pref[jid]) if jid else None))
        if jid:
            pref[jid].append(r[2])
    IDX.frombytes(s3.get_object(Bucket=B, Key=f'{Z4}/_control/disk12_sha64.bin')['Body'].read())
    srt = lambda: all(IDX[i] <= IDX[i + 1] for i in range(0, len(IDX) - 1, 10007))
    if not srt():                      # the extractor reads it natively; accept either byte order
        IDX.byteswap()
    assert srt(), 'index not sorted'
    print(f'index {len(IDX)} archives {len(jobs)} sds2 rows {len(rows)} (unmapped {sum(1 for x in rowref if x[0] is None)})', flush=True)
    args = [(j['id'], akey[j['id']], pref.get(j['id'], [])) for j in sorted(jobs, key=lambda j: -j['size'])]
    models = collections.defaultdict(lambda: {'size': 0, 'paths': [], 'keys': set(), 'dedup': set()})
    sdsrows = {}; errs = []
    with ProcessPoolExecutor(a.procs) as ex:
        for n, (jid, ms, sds, err) in enumerate(ex.map(scan, args, chunksize=4)):
            if err:
                errs.append([jid, err]); continue
            for sha, size, p, key, dd in ms:
                m = models[sha]; m['size'] = size; m['paths'].append(akey[jid] + '/' + p)
                if key and key.startswith('cad-disk-extract/'):
                    m['keys'].add(key)
                if dd:
                    m['dedup'].add(dd)
            for i, lst in sds.items():
                sdsrows[(jid, i)] = lst
            if n % 100 == 0:
                print(f'{n}/{len(args)} manifests {time.time()-t0:.0f}s models={len(models)}', flush=True)
    print(f'scanned {len(args)} manifests in {time.time()-t0:.0f}s, errors {len(errs)}', flush=True)

    # ---- model files: new = sha not in the Disk-1/2 index
    by = collections.defaultdict(list); stat = collections.Counter()
    need_marker = []
    for sha, m in models.items():
        exts = collections.Counter(ext_of(p) for p in m['paths'])
        e = exts.most_common(1)[0][0]
        e = {'.step': '.stp'}.get(e, e)
        d12 = in_d12(sha) or 'disk12' in m['dedup']
        stat[(e, 'disk12' if d12 else 'new')] += 1
        if d12 or m['size'] == 0:
            if m['size'] == 0: stat[(e, 'empty')] += 1
            continue
        if not m['keys']:
            need_marker.append(sha)
        by[e].append((sha, m))
    with ThreadPoolExecutor(64) as ex:
        for sha, k in zip(need_marker, ex.map(marker, need_marker)):
            if k:
                models[sha]['keys'].add(k)
    missing = [sha for sha in need_marker if not models[sha]['keys']]
    print('stats', dict(stat), 'markers resolved', len(need_marker) - len(missing), 'missing', len(missing), flush=True)

    def mk(sha, m, kind):
        keys = sorted(m['keys'])
        ps = sorted(set(m['paths']))
        return {'id': sha, 'sha256': sha, 'kind': kind, 'input_key': keys[0] if keys else None, 'size': m['size'],
                'n_paths': len(ps), 'paths': ['Zentitude-data-4/' + p for p in ps]}

    ifc = [mk(s, m, e[1:]) for e in ('.ifc', '.ifczip', '.ifcxml') for s, m in by[e]]
    ifc.sort(key=lambda j: -j['size'])
    db1_all = [mk(s, m, 'db1') for s, m in by['.db1']]
    xslib = re.compile(r'^xslib.*\.db1$', re.I)
    db1 = [j for j in db1_all if not all(xslib.match(p.rsplit('/', 1)[-1]) for p in j['paths'])]
    n_xslib = len(db1_all) - len(db1)
    with ThreadPoolExecutor(64) as ex:
        for j, (eng, head) in zip(db1, ex.map(lambda j: db1_engine(j['input_key']) if j['input_key'] else (None, 'nokey'), db1)):
            j['engine'] = eng; j['head'] = head
    db1.sort(key=lambda j: -j['size'])
    stp = [mk(s, m, 'stp') for s, m in by['.stp']]
    stp.sort(key=lambda j: -j['size'])

    def write(k, v):
        p = os.path.join(a.out, k.replace('/', '__'))
        json.dump(v, open(p, 'w'), default=str)
        if not a.dry:
            s3.upload_file(p, B, f'{CONV}/{k}', ExtraArgs={'ContentType': 'application/json'})
    for k, v in (('ifc/jobs.json', ifc), ('db1/jobs.json', db1), ('native_step/index.json', stp)):
        write(k, v)
    print('model job lists written', len(ifc), len(db1), len(stp), f'{time.time()-t0:.0f}s', flush=True)

    # ---- SDS/2 job folders: one job per distinct folder content
    sjobs = {}; srows = []; stored = {}
    for lst in sdsrows.values():                  # keys stored by any SDS/2 folder entry
        for p, sha, size, key, dd in lst:
            if key and key.startswith('cad-disk-extract/'):
                stored.setdefault(sha, key)
    for r, (jid, i) in zip(rows, rowref):
        lst = sdsrows.get((jid, i)) if jid else None
        rec = {'name': r[0], 'archive': r[1], 'path_in_archive': r[2], 'report_files': r[3], 'report_bytes': r[4],
               'report_members': r[5], 'date': r[6], 'archive_id': jid, 'found_files': len(lst or [])}
        srows.append(rec)
        if not lst:
            continue
        lst.sort()
        h = hashlib.sha256('\n'.join(f'{p}\t{s}' for p, s, *_ in lst).encode()).hexdigest()
        rec['content_id'] = h[:24]
        paths = sjobs.setdefault(h, {'rows': [], 'files': lst})['rows']
        paths.append(rec)
    sds2 = []
    for h, v in sjobs.items():
        files = []; nd12 = 0; nmiss = 0; ptr = []
        for p, sha, size, key, dd in v['files']:
            f = {'p': p, 'sha256': sha, 'size': size}
            if key and key.startswith('cad-disk-extract/'):
                f['key'] = key
            elif key and key.startswith('disk12:'):
                f['disk12'] = True; nd12 += 1
            elif size == 0:
                pass
            else:
                ptr.append(f)
            files.append(f)
        # pointer resolution: same content stored elsewhere on data-4 (marker or another model entry)
        for f in ptr:
            k = next(iter(models[f['sha256']]['keys']), None) if f['sha256'] in models else None
            f['key'] = k or stored.get(f['sha256'])
        look = sorted({f['sha256'] for f in ptr if not f['key']})
        with ThreadPoolExecutor(96) as ex:
            for sha, k in zip(look, ex.map(marker, look)):
                stored[sha] = k
        for f in ptr:
            if not f['key']:
                f['key'] = stored.get(f['sha256'])
            if not f['key']:
                nmiss += 1
        r0 = v['rows'][0]
        sds2.append({'id': h[:24], 'name': r0['name'], 'size': sum(f['size'] for f in files), 'n_files': len(files),
                     'n_disk12_files': nd12, 'n_unresolved': nmiss,
                     'paths': ['Zentitude-data-4/%s/%s' % (x['archive'], x['path_in_archive']) for x in v['rows']],
                     'files': files})
    sds2.sort(key=lambda j: -j['size'])
    summ = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'manifests': len(args), 'manifest_errors': errs,
            'model_stats': {f'{k[0]}:{k[1]}': v for k, v in sorted(stat.items())}, 'unresolved_keys': missing[:50], 'n_unresolved': len(missing),
            'ifc_jobs': collections.Counter(j['kind'] for j in ifc), 'db1_jobs': len(db1), 'db1_xslib_excluded': n_xslib,
            'db1_engines': collections.Counter(j['engine'] for j in db1).most_common(), 'stp_new_unique': len(stp),
            'sds2_rows': len(rows), 'sds2_rows_found': sum(1 for r in srows if r['found_files']), 'sds2_jobs': len(sds2),
            'bytes': {'ifc': sum(j['size'] for j in ifc), 'db1': sum(j['size'] for j in db1), 'stp': sum(j['size'] for j in stp),
                      'sds2': sum(j['size'] for j in sds2)}, 'sec': round(time.time() - t0)}
    print(json.dumps(summ, default=str, indent=1), flush=True)
    out = {'sds2/jobs.json': sds2, 'sds2/report_rows.json': srows, 'scan_summary.json': summ}
    for k, v in out.items():
        write(k, v)
    print('written', list(out), flush=True)


if __name__ == '__main__':
    main()
