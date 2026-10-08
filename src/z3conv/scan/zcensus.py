#!/usr/bin/env python3
"""Multi-disk conversion census (read-only on sources; writes only <disk root>/_state/conv2/scan/).

  python3 zcensus.py <disk>        disk = zentitude-data-4 | ... (DISKS below)

Manifest pass (the same rules as the data-3 scan, z3scan.py):
  IFC  = distinct sha256 of .ifc / .ifczip / .ifcxml (and .ifc.gz)
  DB1  = distinct sha256 of .db1 (xslib.db1 component libraries and empty files excluded)
  SDS2 = distinct converter-input fingerprint (fpc: main/jsetup, main/job_mtrl, mem/mem_idx, mem/<n>, subm/subm_idx, subm/<n>);
         the data-3 index id of an SDS2 model is fpc[:24]
Then each distinct content is compared with the data-3 conversion index (current converters): already in data-3 (final, or a
data-3 re-run still open: reused when it finishes) -> no new conversion; the rest is the new work for this disk. Also reported:
the content's key kinds (real object of this disk / this disk's dedup marker / a Disk-1/2 pointer only) and whether the old
data-4 conversion run (old code) had a job for it.
Outputs: <root>/_state/conv2/scan/census.json, parts.tgz (manifest-pass parts, reused by the job builder), local work dir.
"""
import os, sys, json, gzip, time, re, hashlib, collections, subprocess
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import boto3
from botocore.config import Config
try:
    import orjson
    jl = orjson.loads
except ImportError:
    jl = json.loads

B = 'bim-proprietary-data'
Z3 = 'cad-disk-extract/zenitude-data-3'
# reuse_from: conversion indexes of the disks done before this one (a content converted on current code anywhere is reused by sha)
DISKS = {
    'zentitude-data-4': {'root': 'cad-disk-extract/zentitude-data-4', 'old_jobs': 'cad-disk-extract/zentitude-data-4/_control/conv/{p}/jobs.json',
                         'reuse_from': [('zenitude-data-3', f'{Z3}/_state/conv')]},
}
DISK = sys.argv[1] if len(sys.argv) > 1 else 'zentitude-data-4'
CFG = DISKS[DISK]
ROOT = CFG['root']
OUT = f'{ROOT}/_state/conv2/scan'
W = os.environ.get('CENSUS_WORK', f'/opt/zcensus/{DISK}')
NPROC = int(os.environ.get('CENSUS_PROCS', str(max(4, (os.cpu_count() or 8) // 2))))
IFC_EXT = ('ifc', 'ifczip', 'ifcxml')
MODEL_DIRS = ('main/', 'mem/', 'subm/')
CONV_IN = re.compile(r'^(main/(jsetup|job_mtrl)|mem/(mem_idx|\d+)|subm/(subm_idx|\d+))$')
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 40, 'mode': 'standard'},
                                                                            max_pool_connections=64, connect_timeout=30, read_timeout=300))
    return _c['c']


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def log(*a):
    print(now(), *a, flush=True)


def put(key, body):
    assert key.startswith(OUT + '/'), key                     # census writes only its own prefix
    s3().put_object(Bucket=B, Key=key, Body=body)


def getj(key):
    try:
        b = s3().get_object(Bucket=B, Key=key)['Body'].read()
    except Exception:
        return None
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    return json.loads(b)


def lst(prefix):
    out = []
    for pg in s3().get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=prefix):
        out += pg.get('Contents', [])
    return out


def ext_of(base):
    b = base.lower()
    if b.endswith('.ifc.gz'):
        return 'ifc'
    return b.rsplit('.', 1)[-1] if '.' in b else ''


def kind_of(k):
    k = k or ''
    if k.startswith('disk12:'):
        return 'disk12'
    if k.startswith('sha256:'):
        return 'marker'
    if k.startswith('prior:'):
        return 'prior'
    if k.startswith('src:'):
        return 'src'
    return 'real' if k else 'none'


def model_split(p):
    pl = p.lower(); out = []
    for d in MODEL_DIRS:
        i = pl.find(d)
        while i >= 0:
            if i == 0 or pl[i - 1] == '/':
                out.append((p[:i], p[i:]))
            i = pl.find(d, i + 1)
    return out


def pass_one(mkey):
    jid = mkey.rsplit('/', 1)[-1].split('.jsonl')[0]
    outp = os.path.join(W, 'parts', jid + '.json.gz')
    if os.path.exists(outp):
        return jid, 'cached'
    tmp = os.path.join(W, 'm', jid + '.jsonl.gz')
    for attempt in range(5):
        try:
            s3().download_file(B, mkey, tmp); break
        except Exception as e:
            if attempt == 4:
                return jid, f'download_error {e}'
            time.sleep(5 * (attempt + 1))
    ifc, db1, roots, n, nosha = [], [], {}, 0, 0
    with gzip.open(tmp, 'rb') as fh:
        for line in fh:
            if len(line) < 3:
                continue
            e = jl(line); n += 1
            p = e.get('path') or ''; base = p[p.rfind('/') + 1:]; lb = base.lower(); x = ext_of(base)
            sha = e.get('sha256')
            if x in IFC_EXT or x == 'db1':
                if not sha:
                    nosha += 1; continue
                (ifc if x in IFC_EXT else db1).append([p, e.get('size') or 0, sha, e.get('key') or ''])   # key kept for the job builder
            if lb == 'jsetup' and p[:len(p) - len(base)].lower().endswith('main/'):
                roots.setdefault(p[:len(p) - len(base) - 5], [])
    if roots:
        with gzip.open(tmp, 'rb') as fh:
            for line in fh:
                if len(line) < 3:
                    continue
                e = jl(line); p = e.get('path') or ''
                for r, rel in model_split(p):
                    if r in roots and e.get('sha256'):
                        roots[r].append([rel, e.get('size') or 0, e['sha256'], e.get('key') or ''])
    os.remove(tmp)
    sds = []
    for r, fl in roots.items():
        fl.sort()
        fp = hashlib.sha256('\n'.join(f'{rel.lower()}\t{sha}' for rel, _, sha, _ in fl).encode()).hexdigest()
        fpc = hashlib.sha256('\n'.join(sorted(f'{rel.lower()}\t{sha}' for rel, _, sha, _ in fl if CONV_IN.match(rel.lower()))).encode()).hexdigest()
        rp = os.path.join(W, 'roots', fp + '.json.gz')
        if not os.path.exists(rp):
            with gzip.open(rp + f'.{os.getpid()}', 'wt') as g:
                json.dump(fl, g)
            os.replace(rp + f'.{os.getpid()}', rp)
        js = next((x[2] for x in fl if x[0].lower() == 'main/jsetup'), None)
        sds.append({'root': r, 'fp': fp, 'fpc': fpc, 'jsetup': js, 'n_model': len(fl), 'model_bytes': sum(x[1] for x in fl),
                    'kinds': dict(collections.Counter(kind_of(x[3]) for x in fl)),
                    'complete': any(x[0].lower() == 'main/job_mtrl' for x in fl) and any(x[0].lower() == 'mem/mem_idx' for x in fl)})
    doc = {'id': jid, 'manifest': mkey, 'rows': n, 'no_sha': nosha, 'ifc': ifc, 'db1': db1, 'sds2': sds}
    with gzip.open(outp + '.tmp', 'wt') as g:
        json.dump(doc, g)
    os.replace(outp + '.tmp', outp)
    return jid, f'rows={n} ifc={len(ifc)} db1={len(db1)} sds2={len(sds)}'


def main():
    for d in ('parts', 'm', 'roots'):
        os.makedirs(os.path.join(W, d), exist_ok=True)
    mans = [o for o in lst(f'{ROOT}/_state/manifests/') if '.jsonl' in o['Key']]
    log(f'{DISK}: {len(mans)} manifests ({sum(o["Size"] for o in mans) / 1e9:.1f} GB) e.g. {[o["Key"] for o in mans[:2]]}; procs {NPROC}')
    if not mans:
        log('no manifests under', f'{ROOT}/_state/manifests/', '; top-level _state prefixes:',
            [p['Prefix'] for p in s3().list_objects_v2(Bucket=B, Prefix=f'{ROOT}/_state/', Delimiter='/').get('CommonPrefixes', [])][:40])
        sys.exit(2)
    mans.sort(key=lambda o: -o['Size'])
    t0 = time.time(); errs = []; done = 0
    with ProcessPoolExecutor(NPROC) as ex:
        for jid, msg in ex.map(pass_one, [o['Key'] for o in mans], chunksize=1):
            done += 1
            if 'error' in msg:
                errs.append([jid, msg])
            if done % 100 == 0 or done == len(mans):
                log(f'pass {done}/{len(mans)} {time.time() - t0:.0f}s errors={len(errs)}')
    if errs:
        log('ERRORS (re-run to retry):', errs[:10]); sys.exit(3)

    # ---- aggregate
    IFC, DB1, SDS = {}, {}, {}
    rows = nosha = 0
    for fn in sorted(os.listdir(os.path.join(W, 'parts'))):
        d = json.load(gzip.open(os.path.join(W, 'parts', fn), 'rt'))
        rows += d['rows']; nosha += d['no_sha']
        for p, size, sha, k in d['ifc']:
            c = IFC.setdefault(sha, {'size': size, 'n': 0, 'kinds': set(), 'ext': ext_of(p[p.rfind('/') + 1:])})
            c['n'] += 1; c['kinds'].add(kind_of(k))
        for p, size, sha, k in d['db1']:
            c = DB1.setdefault(sha, {'size': size, 'n': 0, 'kinds': set(), 'xslib': True})
            c['n'] += 1; c['kinds'].add(kind_of(k))
            if p[p.rfind('/') + 1:].lower() != 'xslib.db1':
                c['xslib'] = False
        for r in d['sds2']:
            c = SDS.setdefault(r['fpc'], {'bytes': 0, 'n': 0, 'kinds': collections.Counter(), 'complete': False, 'fps': set(), 'jsetup': r.get('jsetup')})
            c['n'] += 1; c['bytes'] = max(c['bytes'], r['model_bytes']); c['kinds'].update(r['kinds']); c['fps'].add(r['fp'])
            c['complete'] = c['complete'] or r['complete']
    DB1x = {s: c for s, c in DB1.items() if not c['xslib'] and c['size'] > 0}
    log(f'aggregated: rows {rows}, IFC {len(IFC)}, DB1 {len(DB1x)} (+{len(DB1) - len(DB1x)} xslib/empty), SDS2 {len(SDS)}')

    # ---- conversion indexes of the earlier disks (current converters) + their open re-runs / pending jobs
    idx = {'ifc': {}, 'db1': {}, 'sds2': {}}; open3 = {'ifc': set(), 'db1': set(), 'sds2': set()}
    js_known = collections.defaultdict(set)              # SDS2 jsetup sha -> earlier disks holding a revision family
    for dname, st in CFG['reuse_from']:
        raw = s3().get_object(Bucket=B, Key=f'{st}/index.jsonl.gz')['Body'].read()
        for l in gzip.decompress(raw).decode().splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            p = r.get('pipeline')
            if p in idx and r['id'] not in idx[p]:
                idx[p][r['id']] = {'class': r.get('class'), 'code': r.get('converter_code'), 'disk': dname}
                if p == 'sds2' and r.get('jsetup_sha256'):
                    js_known[r['jsetup_sha256']].add(dname)
        for p in ('ifc', 'db1', 'sds2'):
            open3[p] |= set(getj(f'{st}/{p}/redo.json') or [])
            open3[p] |= {j['id'] for j in (getj(f'{st}/{p}/jobs_reconvert.json') or []) if isinstance(j, dict)}
            open3[p] |= {j['id'] for j in (getj(f'{st}/{p}/jobs.json') or []) if isinstance(j, dict) and j.get('id') not in idx[p]}
    old = {}
    for p in ('ifc', 'db1', 'sds2'):
        j = getj(CFG['old_jobs'].format(p=p)) or []
        j = j.get('jobs') if isinstance(j, dict) else j
        old[p] = {x.get('sha256') or x.get('id') for x in j or [] if isinstance(x, dict)}
        if p == 'sds2':
            old[p] |= {x.get('fpc') for x in j or [] if isinstance(x, dict) and x.get('fpc')}

    def classify(p, key, d3id, size, kinds):
        if d3id in idx[p]:
            return 'reused_open_rerun' if d3id in open3[p] else 'reused_final'
        if d3id in open3[p]:
            return 'reused_queued_earlier_disk'          # queued (not yet converted) on an earlier disk: converted there once
        return 'new'

    summ = {'disk': DISK, 'updated': now(), 'manifests': len(mans), 'manifest_rows': rows, 'model_rows_without_sha': nosha,
            'reuse_index_rows': {p: len(v) for p, v in idx.items()}, 'reuse_from': [d for d, _ in CFG['reuse_from']]}
    for p, D, idf, szf in (('ifc', IFC, lambda s: s, 'size'), ('db1', DB1x, lambda s: s, 'size'), ('sds2', SDS, lambda f: f[:24], 'bytes')):
        act = collections.Counter(); byt = collections.Counter(); kk = collections.Counter(); cls3 = collections.Counter()
        oldn = collections.Counter(); szb = collections.Counter()
        for key, c in D.items():
            a = classify(p, key, idf(key), c[szf], c['kinds'])
            act[a] += 1; byt[a] += c[szf]
            if a != 'new':
                if idf(key) in idx[p]:
                    cls3[str(idx[p][idf(key)]['class'])] += 1
                continue
            ks = set(c['kinds']) if p != 'sds2' else {k for k, v in c['kinds'].items() if v}
            kk['real_or_marker' if ks & {'real', 'marker', 'src'} else ('disk12_only' if ks <= {'disk12', 'prior'} else '+'.join(sorted(ks)))] += 1
            oldn['in_old_data4_jobs' if key in old[p] else 'not_in_old_data4_jobs'] += 1
            mb = c[szf] / 2 ** 20
            szb['<10MB' if mb < 10 else '10-100MB' if mb < 100 else '100-500MB' if mb < 500 else '>=500MB'] += 1
        summ[p] = {'distinct': len(D), 'raw_occurrences': sum(c['n'] for c in D.values()), 'by_action': dict(act),
                   'bytes_by_action_GB': {k: round(v / 1e9, 1) for k, v in byt.items()}, 'data3_classes_of_reused': dict(cls3),
                   'new_key_kinds': dict(kk), 'new_vs_old_data4_jobs': dict(oldn), 'new_by_size': dict(szb)}
        if p == 'ifc':
            summ[p]['by_ext'] = dict(collections.Counter(c['ext'] for c in D.values()))
        if p == 'sds2':
            newk = [k for k, c in D.items() if classify(p, k, k[:24], 0, None) == 'new']
            summ[p]['new_incomplete_layout'] = sum(1 for k in newk if not D[k]['complete'])
            # (owner) one primary per jsetup across all disks: new SDS2 contents whose jsetup family already exists on an earlier disk
            # are revisions there (the global revision ranking decides the primary); the rest are new families
            summ[p]['new_jsetup_family_on_earlier_disk'] = sum(1 for k in newk if D[k].get('jsetup') in js_known)
            summ[p]['new_jsetup_families'] = len({D[k].get('jsetup') for k in newk if D[k].get('jsetup') not in js_known})
            summ[p]['distinct_full_folders'] = sum(len(c['fps']) for c in D.values())
    put(f'{OUT}/census.json', json.dumps(summ, indent=1).encode())
    subprocess.run(['tar', 'czf', os.path.join(W, 'parts.tgz'), '-C', W, 'parts', 'roots'], check=True)
    s3().upload_file(os.path.join(W, 'parts.tgz'), B, f'{OUT}/parts.tgz')
    log('CENSUS', json.dumps(summ))


if __name__ == '__main__':
    main()
