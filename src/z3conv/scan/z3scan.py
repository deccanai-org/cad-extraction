#!/usr/bin/env python3
"""Zenitude-data-3 conversion scan: manifests -> distinct IFC / DB1 / SDS2 contents -> resolved input keys -> reuse of earlier
conversions (Disk-1/2, data-4) proven by sha256 -> job lists for the conversion and grading fleets.

Runs on the coordinator box (instance role: reads both buckets, writes bim cad-disk-extract/zenitude-data-3/ only).
  python3 z3scan.py [phase ...]     phases: a (manifest pass), b (aggregate+resolve+reuse+jobs); default: a b
Local work dir $SCAN_WORK (default /work/scan). Outputs (bim):
  zenitude-data-3/_state/conv/scan/            parts per manifest, summary.json, contents_{ifc,db1,sds2}.jsonl.gz
  zenitude-data-3/_state/conv/<pipe>/jobs.json conversion jobs (largest first)  pipe = ifc | db1 | sds2
  zenitude-data-3/_state/conv/sds2/files/<fp>.json.gz   model files (main/ mem/ subm/) of each distinct SDS2 job, keys resolved
  zenitude-data-3/_state/conv/grade/jobs.json  reused STEP that need (re-)grading under the data-3 class rules

Dedup rules (one conversion per distinct content):
  IFC  = sha256 of the file (.ifc / .ifczip / .ifcxml)
  DB1  = sha256 of the .db1 (the converter reads only the .db1; xslib.db1 component libraries excluded)
  SDS2 = fingerprint over the job's model files: sha256 of sorted "<path below the job root, lower-case>\\t<sha256>" lines for
         every file under main/ mem/ subm/ (what the converter reads). main/jsetup sha256 recorded too (the stats rule).
Key resolution per sha: real data-3 key > src: loose source key > data-3 marker (sha256:) > data-4 marker / data-4 manifest
  row (prior:) > Disk-1/2 (DB1 via db1_jobs sha->key; IFC via size candidates + sha256 proof) > unresolved.
"""
import os, sys, json, gzip, time, re, hashlib, collections, subprocess, traceback
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
try:
    import orjson
    jl = orjson.loads
except ImportError:
    jl = json.loads

B = 'bim-proprietary-data'
ROOT = 'cad-disk-extract/zenitude-data-3'
Z4 = 'cad-disk-extract/zentitude-data-4'
D12 = 'cad-disk-extract'
CB = 'annotationprod'
JOBS_KEY = 'cad-disk-extract/_control/move/z3/jobs.json'
ST = f'{ROOT}/_state/conv'
W = os.environ.get('SCAN_WORK', '/work/scan')
NPROC = int(os.environ.get('SCAN_PROCS', str(max(4, (os.cpu_count() or 8) - 4))))
IFC_EXT = ('ifc', 'ifczip', 'ifcxml')
MODEL_DIRS = ('main/', 'mem/', 'subm/')
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 40, 'mode': 'standard'},
                                                                            max_pool_connections=128, connect_timeout=30, read_timeout=300))
    return _c['c']


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def log(*a):
    print(now(), *a, flush=True)


def put_json(key, obj, gz=False):
    assert key.startswith(ROOT + '/'), key
    body = json.dumps(obj, default=str).encode()
    if gz:
        body = gzip.compress(body, 6)
    s3().put_object(Bucket=B, Key=key, Body=body, ContentType='application/json')


def put_file(key, path):
    assert key.startswith(ROOT + '/'), key
    s3().upload_file(path, B, key)


def getj(bucket, key):
    try:
        body = s3().get_object(Bucket=bucket, Key=key)['Body'].read()
    except ClientError:
        return None
    if body[:2] == b'\x1f\x8b':
        body = gzip.decompress(body)
    return json.loads(body)


def get_text(bucket, key):
    try:
        return s3().get_object(Bucket=bucket, Key=key)['Body'].read().decode().strip()
    except ClientError:
        return None


def head(bucket, key, checksum=False):
    try:
        kw = {'ChecksumMode': 'ENABLED'} if checksum else {}
        return s3().head_object(Bucket=bucket, Key=key, **kw)
    except ClientError:
        return None


def lst(bucket, prefix):
    out = []
    for page in s3().get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        out += page.get('Contents', [])
    return out


def ext_of(base):
    b = base.lower()
    if b.endswith('.ifc.gz'):
        return 'ifc'
    return b.rsplit('.', 1)[-1] if '.' in b else ''


CONV_IN = re.compile(r'^(main/(jsetup|job_mtrl)|mem/(mem_idx|\d+)|subm/(subm_idx|\d+))$')


def fp_conv(rows):
    """converter-input fingerprint: the files the SDS/2 converter reads (main/jsetup, main/job_mtrl, mem/mem_idx, mem/<n>,
    subm/subm_idx, subm/<n>); rows = [(rel, sha), ...] with rel relative to the job root"""
    return hashlib.sha256('\n'.join(sorted(f'{rel.lower()}\t{sha}' for rel, sha in rows if CONV_IN.match(rel.lower()))).encode()).hexdigest()


def _fpc_of(fp):
    fl = json.load(gzip.open(os.path.join(W, 'roots', fp + '.json.gz'), 'rt'))
    kinds = collections.Counter('prior' if (k or '').startswith('prior:') else 'other' for _, _, _, k, _ in fl)
    return fp, fp_conv([(r[0], r[2]) for r in fl]), kinds['prior']


def model_split(p):
    """-> (job_root_prefix, rel below root) if the path lies under <root>main|mem|subm/, all candidate splits"""
    pl = p.lower(); out = []
    for d in MODEL_DIRS:
        i = pl.find(d)
        while i >= 0:
            if i == 0 or pl[i - 1] == '/':
                out.append((p[:i], p[i:]))
            i = pl.find(d, i + 1)
    return out


# ------------------------------------------------------------------------------------------------ phase A
def pass_a(job):
    jid = job['id']
    outp = os.path.join(W, 'parts', jid + '.json.gz')
    if os.path.exists(outp):
        return jid, 'cached'
    tmp = os.path.join(W, 'm', jid + '.jsonl.gz')
    for attempt in range(5):
        try:
            s3().download_file(B, f'{ROOT}/_state/manifests/{jid}.jsonl.gz', tmp); break
        except Exception as e:
            if attempt == 4:
                return jid, f'download_error {e}'
            time.sleep(5 * (attempt + 1))
    ifc, db1, roots, n, nstp = [], [], {}, 0, 0
    db1_dirs = set()
    with gzip.open(tmp, 'rb') as fh:
        for line in fh:
            if len(line) < 3:
                continue
            p0 = line.find(b'"path"')
            # cheap pre-filter on the path field before a full parse
            e = jl(line); n += 1
            p = e['path']; base = p[p.rfind('/') + 1:]
            lb = base.lower(); x = ext_of(base)
            if x in IFC_EXT:
                ifc.append([p, e.get('size') or 0, e['sha256'], e.get('key') or '', e.get('dedup'), bool(e.get('loose')), e.get('orig_path')])
            elif x == 'db1':
                db1.append([p, e.get('size') or 0, e['sha256'], e.get('key') or '', e.get('dedup'), bool(e.get('loose')), e.get('orig_path')])
                db1_dirs.add(p[:p.rfind('/') + 1])
            elif x in ('stp', 'step'):
                nstp += 1
            if lb in ('jsetup', 'mem_idx'):
                par = p[:len(p) - len(base)]; pl = par.lower()
                if lb == 'jsetup' and pl.endswith('main/'):
                    r = par[:-5]
                    roots.setdefault(r, {}).update(jsetup=e['sha256'], jsetup_size=e.get('size') or 0, jsetup_key=e.get('key'))
                elif lb == 'mem_idx' and pl.endswith('mem/'):
                    roots.setdefault(par[:-4], {})['mem_idx'] = e['sha256']
    files = {r: [] for r in roots}
    tot = {r: [0, 0] for r in roots}
    sib = {d: [] for d in db1_dirs}
    if roots or db1_dirs:
        rkeys = set(roots)
        top = '' in rkeys
        with gzip.open(tmp, 'rb') as fh:
            for line in fh:
                if len(line) < 3:
                    continue
                e = jl(line)
                p = e['path']
                if db1_dirs:
                    d = p[:p.rfind('/') + 1]
                    if d in sib and len(sib[d]) < 3000:
                        sib[d].append([p[len(d):], e.get('size') or 0, e['sha256']])
                if not rkeys:
                    continue
                # total files under any root (for the record)
                i = -1
                while True:
                    pre = p[:i + 1] if i >= 0 else ''
                    if pre in tot:
                        tot[pre][0] += 1; tot[pre][1] += e.get('size') or 0
                    i = p.find('/', i + 1)
                    if i < 0:
                        break
                for r, rel in model_split(p):
                    if r in rkeys:
                        files[r].append([rel, e.get('size') or 0, e['sha256'], e.get('key') or '', e.get('dedup')])
    os.remove(tmp)
    out_roots = []
    for r, meta in roots.items():
        fl = files[r]
        fl.sort()
        fp = hashlib.sha256('\n'.join(f'{rel.lower()}\t{sha}' for rel, _, sha, _, _ in fl).encode()).hexdigest()
        kinds = collections.Counter('prior' if (k or '').startswith('prior:') else ('marker' if (k or '').startswith('sha256:') else
                                    ('src' if (k or '').startswith('src:') else ('real' if k else 'none'))) for _, _, _, k, _ in fl)
        fpath = os.path.join(W, 'roots', fp + '.json.gz')
        if not os.path.exists(fpath):
            tmpf = fpath + f'.{os.getpid()}.tmp'
            with gzip.open(tmpf, 'wt') as g:
                json.dump(fl, g)
            try:
                os.link(tmpf, fpath)
            except FileExistsError:
                pass
            os.remove(tmpf)
        out_roots.append({'root': r, 'fp': fp, 'jsetup': meta.get('jsetup'), 'jsetup_key': meta.get('jsetup_key'),
                          'mem_idx': meta.get('mem_idx'), 'n_model': len(fl), 'model_bytes': sum(x[1] for x in fl),
                          'n_files': tot[r][0], 'bytes': tot[r][1], 'key_kinds': dict(kinds),
                          'has_job_mtrl': any(rel.lower() == 'main/job_mtrl' for rel, *_ in fl),
                          'has_mem_idx': any(rel.lower() == 'mem/mem_idx' for rel, *_ in fl),
                          'has_jsetup': any(rel.lower() == 'main/jsetup' for rel, *_ in fl)})
    prior = sorted({x[2] for x in ifc + db1 if (x[3] or '').startswith('prior:')} |
                   {f[2] for r in files.values() for f in f_iter(r) if (f[3] or '').startswith('prior:')})
    doc = {'id': jid, 'rows': n, 'stp_rows': nstp, 'ifc': ifc, 'db1': [d + [sib.get(d[0][:d[0].rfind('/') + 1], [])] for d in db1],
           'sds2': out_roots, 'prior_shas': prior}
    with gzip.open(outp + '.tmp', 'wt') as g:
        json.dump(doc, g)
    os.replace(outp + '.tmp', outp)
    return jid, f'rows={n} ifc={len(ifc)} db1={len(db1)} sds2={len(out_roots)} prior={len(prior)}'


def f_iter(fl):
    return fl


def phase_a(jobs):
    for d in ('parts', 'm', 'roots'):
        os.makedirs(os.path.join(W, d), exist_ok=True)
    t0 = time.time(); done = 0; errs = []
    # largest manifests first (stats: manifests sizes) so the tail is short
    sizes = {o['Key'].rsplit('/', 1)[-1].split('.')[0]: o['Size'] for o in lst(B, f'{ROOT}/_state/manifests/')}
    jobs = sorted(jobs, key=lambda j: -sizes.get(j['id'], 0))
    with ProcessPoolExecutor(NPROC) as ex:
        for jid, msg in ex.map(pass_a, jobs, chunksize=1):
            done += 1
            if 'error' in msg:
                errs.append([jid, msg])
            if done % 200 == 0 or done == len(jobs):
                log(f'phase A {done}/{len(jobs)} {time.time() - t0:.0f}s errors={len(errs)}')
    if errs:
        log('phase A errors', errs[:20])
    return errs


# ------------------------------------------------------------------------------------------------ phase B helpers
def d4_index(needed_hex):
    """data-4 manifests -> {sha: real stored key} for the needed shas (u64-prefix prefilter)"""
    import numpy as np
    pref = np.array(sorted({int(h[:16], 16) for h in needed_hex}), dtype=np.uint64)
    np.save(os.path.join(W, 'need64.npy'), pref)
    ms = [o['Key'] for o in lst(B, f'{Z4}/_state/manifests/') if o['Key'].endswith('.jsonl.gz')]
    found = {}
    with ProcessPoolExecutor(NPROC) as ex:
        for part in ex.map(_d4_one, ms, chunksize=4):
            for h, k in part.items():
                found.setdefault(h, k)
    want = set(needed_hex)
    return {h: k for h, k in found.items() if h in want}


def _d4_one(key):
    import numpy as np
    pref = np.load(os.path.join(W, 'need64.npy'))
    tmp = os.path.join(W, 'm', 'd4_' + key.rsplit('/', 1)[-1])
    for attempt in range(5):
        try:
            s3().download_file(B, key, tmp); break
        except Exception:
            if attempt == 4:
                return {}
            time.sleep(5)
    out = {}
    with gzip.open(tmp, 'rb') as fh:
        for line in fh:
            if len(line) < 3:
                continue
            i = line.find(b'"sha256": "')
            if i < 0:
                i = line.find(b'"sha256":"'); j = i + 10
            else:
                j = i + 11
            if i < 0:
                continue
            h = int(line[j:j + 16], 16)
            k = np.searchsorted(pref, np.uint64(h))
            if k >= len(pref) or pref[k] != np.uint64(h):
                continue
            e = jl(line)
            kk = e.get('key') or ''
            if kk.startswith(Z4 + '/'):
                out.setdefault(e['sha256'], kk)
    os.remove(tmp)
    return out


def sha256_s3(bucket, key):
    h = hashlib.sha256()
    body = s3().get_object(Bucket=bucket, Key=key)['Body']
    for chunk in iter(lambda: body.read(1 << 22), b''):
        h.update(chunk)
    return h.hexdigest()


def resolve_marker(prefix_root, sha):
    t = get_text(B, f'{prefix_root}/_state/sha/{sha[:2]}/{sha}')
    return t if t and t.startswith('cad-disk-extract/') else None


def _marker_needs(fp, _unused=None):
    fl = json.load(gzip.open(os.path.join(W, 'roots', fp + '.json.gz'), 'rt'))
    a3 = {sha for rel, size, sha, key, dd in fl if key.startswith('sha256:')}
    a4 = {sha for rel, size, sha, key, dd in fl if key.startswith('prior:')}
    return a3, a4


def _markers_chunk(args):
    root, shas = args
    out = {}
    with ThreadPoolExecutor(48) as ex:
        for sha, k in zip(shas, ex.map(lambda h: resolve_marker(root, h), shas)):
            out[sha] = k
    return out


def resolve_markers_parallel(root, shas):
    out = {}
    if not shas:
        return out
    chunks = [(root, shas[i:i + 5000]) for i in range(0, len(shas), 5000)]
    with ProcessPoolExecutor(min(NPROC, 24)) as ex:
        for part in ex.map(_markers_chunk, chunks):
            out.update(part)
    return out


_KM = {}


def _resolve_job(args):
    fpc, fp = args
    if not _KM:
        _KM.update(json.load(open(os.path.join(W, 'keymaps.json'))))
    d4, mk3, mk4 = _KM['d4'], _KM['mk3'], _KM['mk4']
    fl = json.load(gzip.open(os.path.join(W, 'roots', fp + '.json.gz'), 'rt'))
    out = []; unres = 0; kinds = collections.Counter()
    for rel, size, sha, key, dd in fl:
        k, how = None, None
        if key.startswith(ROOT + '/'):
            k, how = key, 'data3'
        elif key.startswith('src:'):
            k, how = key[4:], 'data3_source'
        elif key.startswith('sha256:'):
            k, how = mk3.get(sha), 'data3_marker'
        elif key.startswith('prior:'):
            if sha in d4:
                k, how = d4[sha], 'data4'
            else:
                k, how = mk4.get(sha), 'data4_marker'
        if size == 0 and not k:
            k, how = '', 'empty'
        if k is None:
            unres += 1; how = 'unresolved'
        kinds[how] += 1
        out.append({'p': rel, 'sha256': sha, 'size': size, 'key': k})
    path = os.path.join(W, 'files', fpc + '.json.gz')
    with gzip.open(path, 'wt') as g:
        json.dump(out, g)
    put_file(f'{ST}/sds2/files/{fpc}.json.gz', path)
    return fpc, unres, dict(kinds)


# ------------------------------------------------------------------------------------------------ phase B
def phase_b(jobs):
    jobmap = {j['id']: j for j in jobs}
    arch = {j['id']: (j.get('key') or j.get('dir') or '') for j in jobs}
    IFC = {}; DB1 = {}; SDS = {}; prior_all = set(); stp_rows = 0; rows = 0; sds_rows = []
    parts = sorted(os.listdir(os.path.join(W, 'parts')))
    t0 = time.time()
    for fn in parts:
        if not fn.endswith('.json.gz'):
            continue
        d = json.load(gzip.open(os.path.join(W, 'parts', fn), 'rt'))
        jid = d['id']; a = arch.get(jid, ''); rows += d['rows']; stp_rows += d['stp_rows']
        prior_all.update(d['prior_shas'])
        for p, size, sha, key, dd, loose, orig in d['ifc']:
            c = IFC.setdefault(sha, {'sha256': sha, 'size': size, 'occ': [], 'keys': set()})
            c['occ'].append([jid, a, p]); c['keys'].add(key)
        for p, size, sha, key, dd, loose, orig, sib in d['db1']:
            base = p[p.rfind('/') + 1:].lower()
            c = DB1.setdefault(sha, {'sha256': sha, 'size': size, 'occ': [], 'keys': set(), 'xslib': True, 'siblings': None})
            c['occ'].append([jid, a, p]); c['keys'].add(key)
            if base != 'xslib.db1':
                c['xslib'] = False
            if c['siblings'] is None or len(sib) > len(c['siblings']):
                c['siblings'] = sib
        for r in d['sds2']:
            sds_rows.append((jid, a, r))
    # SDS2: group job folders by converter-input fingerprint; representative = the copy with the fewest prior keys
    fps = sorted({r['fp'] for _, _, r in sds_rows})
    fpc_of = {}; prior_n = {}
    with ProcessPoolExecutor(NPROC) as ex:
        for fp, fpc, npri in ex.map(_fpc_of, fps, chunksize=8):
            fpc_of[fp] = fpc; prior_n[fp] = npri
    for jid, a, r in sds_rows:
        fpc = fpc_of[r['fp']]
        c = SDS.setdefault(fpc, {'fp': None, 'fpc': fpc, 'occ': [], 'full_fps': set(), 'n_files_max': 0, 'bytes_max': 0})
        c['occ'].append([jid, a, r['root']]); c['full_fps'].add(r['fp'])
        c['n_files_max'] = max(c['n_files_max'], r['n_files']); c['bytes_max'] = max(c['bytes_max'], r['bytes'])
        if c['fp'] is None or prior_n[r['fp']] < prior_n[c['fp']] or (prior_n[r['fp']] == prior_n[c['fp']] and r['n_model'] > c['n_model']):
            c.update(fp=r['fp'], rep_occ=[jid, a, r['root']], jsetup=r['jsetup'], n_model=r['n_model'], model_bytes=r['model_bytes'], has_job_mtrl=r['has_job_mtrl'],
                     has_mem_idx=r['has_mem_idx'], has_jsetup=r['has_jsetup'], key_kinds=r['key_kinds'])
    log(f'aggregated {len(parts)} parts: IFC {len(IFC)} distinct, DB1 {len(DB1)} distinct, SDS2 {len(SDS)} distinct converter inputs '
        f'({len(fps)} distinct full folders), '
        f'prior shas {len(prior_all)} ({time.time() - t0:.0f}s)')
    # ---------------- data-4 index for prior shas
    t0 = time.time()
    d4 = d4_index(prior_all) if prior_all else {}
    log(f'data-4 manifest index: {len(d4)}/{len(prior_all)} prior shas found ({time.time() - t0:.0f}s)')

    # ---------------- key resolution
    def pick(c):
        keys = c['keys']; sha = c['sha256']
        real = sorted(k for k in keys if k.startswith(ROOT + '/'))
        if real:
            return real[0], 'data3'
        src = sorted(k[4:] for k in keys if k.startswith('src:'))
        if src:
            return src[0], 'data3_source'
        if any(k.startswith('sha256:') for k in keys):
            t = resolve_marker(ROOT, sha)
            if t:
                return t, 'data3_marker'
        if any(k.startswith('prior:') for k in keys) or True:
            if sha in d4:
                return d4[sha], 'data4'
            t = resolve_marker(Z4, sha)
            if t:
                return t, 'data4_marker'
        return None, 'prior_disk12' if any(k.startswith('prior:') for k in keys) else 'unresolved'

    with ThreadPoolExecutor(64) as ex:
        for c, (k, how) in zip(list(IFC.values()), ex.map(pick, list(IFC.values()))):
            c['input_key'] = k; c['input_from'] = how
        for c, (k, how) in zip(list(DB1.values()), ex.map(pick, list(DB1.values()))):
            c['input_key'] = k; c['input_from'] = how

    # ---------------- Disk-1/2 lookups
    # DB1: db1_jobs sha -> key; Windows pipeline outputs by sha
    d12db1 = {j['sha']: j for j in (getj(B, f'{D12}/_control/db1-v2/db1_jobs.json') or {}).get('jobs', [])}
    for c in DB1.values():
        if c['input_key'] is None and c['sha256'] in d12db1:
            c['input_key'] = d12db1[c['sha256']]['key']; c['input_from'] = 'disk12_db1_jobs'
    # IFC: Disk-1/2 results by size, proven by sha256 of the source object
    d12res = {}
    for o in lst(B, f'{D12}/_state/ifc-step/results/'):
        if o['Key'].endswith('.json'):
            d12res[o['Key'].rsplit('/', 1)[-1][:-5]] = o
    log(f'Disk-1/2 IFC results: {len(d12res)}')
    bysize = collections.defaultdict(list)
    for rid in d12res:
        try:
            et, sz = rid.rsplit('_', 1); bysize[int(sz)].append(rid)
        except ValueError:
            pass
    need = [c for c in IFC.values() if c['input_from'] in ('prior_disk12', 'unresolved') or c['input_from'].startswith('data4')]
    # every prior IFC may be a Disk-1/2 conversion; only candidates of equal size are hashed
    cand_jobs = []
    for c in IFC.values():
        if not any(k.startswith('prior:') for k in c['keys']):
            continue
        for rid in bysize.get(c['size'], []):
            cand_jobs.append((c['sha256'], rid))
    log(f'Disk-1/2 IFC size candidates: {len(cand_jobs)} pairs for {len({s for s, _ in cand_jobs})} prior IFC')
    d12meta = {}

    def load_res(rid):
        return rid, getj(B, d12res[rid]['Key'])
    rids = sorted({r for _, r in cand_jobs})
    with ThreadPoolExecutor(64) as ex:
        for rid, r in ex.map(load_res, rids):
            d12meta[rid] = r
    hashed = {}

    def hash_rid(rid):
        r = d12meta.get(rid) or {}
        k = r.get('key')
        if not k:
            return rid, None
        # packages that gained a STEP moved from dataset/main/2d/ to 3d/ after the IFC run recorded the key
        alts = [k] + ([k.replace('/dataset/main/2d/', '/dataset/main/3d/', 1)] if '/dataset/main/2d/' in k else []) + \
               ([k.replace('/dataset/main/3d/', '/dataset/main/2d/', 1)] if '/dataset/main/3d/' in k else [])
        for kk in alts:
            if head(B, kk) is None:
                continue
            try:
                r['key_found'] = kk
                return rid, sha256_s3(B, kk)
            except Exception:
                continue
        return rid, None
    with ThreadPoolExecutor(32) as ex:
        for rid, h in ex.map(hash_rid, rids):
            hashed[rid] = h
    d12_by_sha = collections.defaultdict(list)
    for rid, h in hashed.items():
        if h:
            d12_by_sha[h].append(rid)
    for c in IFC.values():
        rs = d12_by_sha.get(c['sha256'], [])
        if rs:
            c['disk12_ifc'] = [{'id': rid, 'result_key': d12res[rid]['Key'], 'source_key': (d12meta[rid] or {}).get('key_found') or (d12meta[rid] or {}).get('key'),
                                'status': (d12meta[rid] or {}).get('status'), 'out_key': (d12meta[rid] or {}).get('out_key')} for rid in rs]
            if c['input_key'] is None:
                c['input_key'] = c['disk12_ifc'][0]['source_key']; c['input_from'] = 'disk12_proven_sha'

    # ---------------- reuse: IFC
    def d4_ifc(c):
        return c['sha256'], getj(B, f'{Z4}/_state/conv/ifc/results/{c["sha256"]}.json')
    with ThreadPoolExecutor(64) as ex:
        for sha, r in ex.map(d4_ifc, [c for c in IFC.values() if any(k.startswith('prior:') for k in c['keys'])]):
            if r:
                IFC[sha]['data4_ifc'] = r
    # ---------------- reuse: DB1
    def d4_db1(c):
        sha = c['sha256']
        return sha, (getj(B, f'{Z4}/_state/conv/db1/results/{sha}.json'), getj(B, f'{D12}/_state/db1-v2/results/{sha}.json'),
                     getj(B, f'{D12}/derived/db1-step/Disk-1/by-sha256/{sha}/result.json'))
    with ThreadPoolExecutor(64) as ex:
        for sha, (r4, r12, rw) in ex.map(d4_db1, [c for c in DB1.values() if any(k.startswith('prior:') for k in c['keys'])]):
            if r4: DB1[sha]['data4_db1'] = r4
            if r12: DB1[sha]['disk12_db1'] = r12
            if rw: DB1[sha]['disk12_windows'] = rw
            if sha in d12db1: DB1[sha]['disk12_db1_job'] = d12db1[sha]
    # DB1 still without an input copy: the earlier runs' own source keys (Windows pipeline result.json, Disk-1/2 v2 result)
    def alt_db1(c):
        for k in ((c.get('disk12_windows') or {}).get('source_key'), (c.get('disk12_db1') or {}).get('input_key'),
                  (c.get('disk12_db1') or {}).get('key'), (c.get('data4_db1') or {}).get('input_key')):
            if k and head(B, k):
                return c['sha256'], k
        return c['sha256'], None
    with ThreadPoolExecutor(32) as ex:
        for sha, k in ex.map(alt_db1, [c for c in DB1.values() if c['input_key'] is None]):
            if k:
                DB1[sha]['input_key'] = k; DB1[sha]['input_from'] = 'disk12_prior_result_source_key'

    # ---------------- SDS2: data-4 fingerprints + Disk-2 run-2 by archive identity
    d4jobs = getj(B, f'{Z4}/_control/conv/sds2/jobs.json') or []

    def d4fp(j):
        if not j.get('files_key'):
            return j['id'], None
        fl = getj(B, j['files_key']) or []
        root = j.get('job_root') or ''
        pre = len(root) + 1 if root else 0
        return j['id'], fp_conv([(f['p'][pre:], f['sha256']) for f in fl])
    d4fps = {}
    with ThreadPoolExecutor(32) as ex:
        for jid, fp in ex.map(d4fp, d4jobs):
            if fp:
                d4fps.setdefault(fp, []).append(jid)
    for fp, ids in d4fps.items():
        if fp in SDS:
            SDS[fp]['data4_sds2'] = [{'id': i, 'result': getj(B, f'{Z4}/_state/conv/sds2/results/{i}.json')} for i in ids]
    log(f'data-4 SDS2 fingerprint matches: {sum(1 for c in SDS.values() if c.get("data4_sds2"))}')
    r2 = {}
    R2 = f'{D12}/sds2-step-r2-20260929-01'
    for o in lst(B, f'{R2}/shards/'):
        if o['Key'].endswith('/results.jsonl'):
            shard = o['Key'].split('/')[-2]
            for line in s3().get_object(Bucket=B, Key=o['Key'])['Body'].read().decode('utf-8', 'replace').splitlines():
                try:
                    x = json.loads(line)
                except Exception:
                    continue
                x['_shard'] = shard
                r2.setdefault((x.get('archive') or '', (x.get('job_root') or '').strip('/')), []).append(x)
    # shard-00 switched to the v6 candidate converter mid-run: its rows come from the checkpoint written before the switch (v4)
    pre_v6 = {}
    try:
        for line in s3().get_object(Bucket=B, Key=f'{R2}/control/checkpoints/shard00_before_v6.jsonl')['Body'].read().decode('utf-8', 'replace').splitlines():
            try:
                x = json.loads(line); x['_shard'] = 'shard-00'
                pre_v6.setdefault((x.get('archive') or '', (x.get('job_root') or '').strip('/')), []).append(x)
            except Exception:
                pass
    except Exception:
        pass
    dropped = 0
    for k in list(r2):
        keep = [x for x in r2[k] if x['_shard'] != 'shard-00']
        dropped += len(r2[k]) - len(keep)
        if keep:
            r2[k] = keep
        else:
            del r2[k]
    for k, rows_ in pre_v6.items():
        r2.setdefault(k, []).extend(rows_)
    log(f'run-2 result rows: {sum(len(v) for v in r2.values())} keys {len(r2)} (shard-00 results.jsonl rows dropped: {dropped}; '
        f'replaced by {sum(len(v) for v in pre_v6.values())} pre-v6 checkpoint rows)')
    ident = {}

    def archive_identity(arel):
        a = head(B, f'Disk-2/{arel}', True); b = head(B, f'Zenitude-data-3/{arel}', True)
        if not a or not b:
            return arel, None
        if a['ContentLength'] != b['ContentLength']:
            return arel, {'same': False, 'why': 'size'}
        for f in ('ChecksumSHA256', 'ChecksumCRC64NVME'):
            if a.get(f) and b.get(f) and a.get('ChecksumType', 'FULL_OBJECT') == b.get('ChecksumType', 'FULL_OBJECT'):
                return arel, {'same': a[f] == b[f], 'by': f}
        if a['ETag'] == b['ETag']:
            return arel, {'same': True, 'by': 'etag+size'}
        # Disk-2 copies carry a full-object SHA-256, data-3 copies CRC64NVME: hash the data-3 copy and compare
        if a.get('ChecksumSHA256') and a.get('ChecksumType', 'FULL_OBJECT') == 'FULL_OBJECT':
            import base64
            try:
                h = hashlib.sha256()
                body = s3().get_object(Bucket=B, Key=f'Zenitude-data-3/{arel}')['Body']
                for chunk in iter(lambda: body.read(8 << 20), b''):
                    h.update(chunk)
                return arel, {'same': base64.b64encode(h.digest()).decode() == a['ChecksumSHA256'], 'by': 'sha256(data-3 copy) vs Disk-2 ChecksumSHA256',
                              'bytes': b['ContentLength']}
            except Exception as e:
                return arel, {'same': None, 'why': f'hash error {type(e).__name__}'}
        return arel, {'same': None, 'why': 'etag differs, no comparable checksum'}
    want = set()
    for c in SDS.values():
        for jid, a, root in c['occ']:
            if a.startswith('Zenitude-data-3/') and '!/' not in root:
                arel = a[len('Zenitude-data-3/'):]
                if (arel, root.strip('/')) in r2:
                    want.add(arel)
    with ThreadPoolExecutor(32) as ex:
        for arel, v in ex.map(archive_identity, sorted(want)):
            ident[arel] = v
    json.dump(ident, open(os.path.join(W, 'archive_identity.json'), 'w'), indent=0)
    put_file(f'{ST}/scan/archive_identity.json', os.path.join(W, 'archive_identity.json'))
    n_r2 = 0
    for c in SDS.values():
        for jid, a, root in c['occ']:
            if not a.startswith('Zenitude-data-3/') or '!/' in root:
                continue
            arel = a[len('Zenitude-data-3/'):]
            rows_ = r2.get((arel, root.strip('/')))
            if rows_ and (ident.get(arel) or {}).get('same'):
                c.setdefault('disk2_run2', []).append({'archive': arel, 'job_root': root.strip('/'), 'identity': ident[arel], 'rows': rows_})
        if c.get('disk2_run2'):
            n_r2 += 1
    log(f'run-2 proven matches (same archive bytes + same job root): {n_r2}; archive identity checked {len(ident)} '
        f'same={sum(1 for v in ident.values() if v and v.get("same"))}')

    # ---------------- SDS2 model-file key resolution (per distinct job; markers resolved once per unique sha, in parallel)
    os.makedirs(os.path.join(W, 'files'), exist_ok=True)
    t0 = time.time()
    reps = [c['fp'] for c in SDS.values()]
    need3, need4 = set(), set()
    with ProcessPoolExecutor(NPROC) as ex:
        for a3, a4 in ex.map(_marker_needs, reps, [list(d4.keys()) if False else None] * len(reps), chunksize=8):
            need3.update(a3); need4.update(a4)
    need4 -= set(d4)
    log(f'SDS2 marker lookups: data-3 {len(need3)} shas, data-4 {len(need4)} shas')
    mk3 = resolve_markers_parallel(ROOT, sorted(need3))
    mk4 = resolve_markers_parallel(Z4, sorted(need4))
    log(f'markers resolved: data-3 {sum(1 for v in mk3.values() if v)}/{len(mk3)}, data-4 {sum(1 for v in mk4.values() if v)}/{len(mk4)} ({time.time() - t0:.0f}s)')
    json.dump({'d4': d4, 'mk3': mk3, 'mk4': mk4}, open(os.path.join(W, 'keymaps.json'), 'w'))
    with ProcessPoolExecutor(NPROC) as ex:
        for fpc, unres, kinds in ex.map(_resolve_job, [(c['fpc'], c['fp']) for c in SDS.values()], chunksize=4):
            SDS[fpc]['unresolved'] = unres; SDS[fpc]['resolved_from'] = kinds
    log(f'SDS2 model files resolved for {len(SDS)} jobs ({time.time() - t0:.0f}s); jobs with unresolved files: '
        f'{sum(1 for c in SDS.values() if c["unresolved"])}')

    # ---------------- write contents + jobs
    write_outputs(IFC, DB1, SDS, rows, stp_rows, jobmap)


def occ_paths(c, n=20):
    return [f'{a} :: {p}' for _, a, p in c['occ'][:n]]


def ok_result(r):
    return bool(r) and r.get('status') == 'ok'


def write_outputs(IFC, DB1, SDS, rows, stp_rows, jobmap):
    os.makedirs(os.path.join(W, 'out'), exist_ok=True)
    ifc_jobs, db1_jobs, sds_jobs, grade_jobs = [], [], [], []
    summ = {'updated': now(), 'manifest_rows': rows, 'native_stp_rows': stp_rows}

    # IFC
    cnt = collections.Counter()
    with gzip.open(os.path.join(W, 'out', 'contents_ifc.jsonl.gz'), 'wt') as g:
        for sha, c in sorted(IFC.items()):
            kind = ext_of(c['occ'][0][2])
            row = {'pipeline': 'ifc', 'id': sha, 'sha256': sha, 'size': c['size'], 'kind': kind, 'n_paths': len(c['occ']),
                   'paths': occ_paths(c), 'input_key': c['input_key'], 'input_from': c['input_from'],
                   'prior': any(k.startswith('prior:') for k in c['keys'])}
            reuse = None
            r4 = c.get('data4_ifc')
            if ok_result(r4):
                reuse = {'from': 'data-4', 'step_key': r4.get('out_key') or (r4.get('step') or {}).get('key'), 'result_key': f'{Z4}/_state/conv/ifc/results/{sha}.json'}
            elif c.get('disk12_ifc'):
                okd = [x for x in c['disk12_ifc'] if x['status'] == 'ok']
                if okd:
                    reuse = {'from': 'disk-1/2', 'step_key': okd[0]['out_key'], 'result_key': okd[0]['result_key']}
            row['reuse'] = reuse
            if reuse:
                row['action'] = 'reuse'; grade_jobs.append({'id': 'ifc-' + sha, 'pipeline': 'ifc', 'sha256': sha, 'size': c['size'], 'kind': kind,
                                                            'input_key': c['input_key'], 'step_key': reuse['step_key'], 'result_key': reuse['result_key'],
                                                            'reuse_from': reuse['from'], 'n_paths': len(c['occ']), 'paths': occ_paths(c, 5)})
            elif r4 and r4.get('status') != 'ok':
                row['action'] = 'failed_before_same_converter'; row['prior_result_key'] = f'{Z4}/_state/conv/ifc/results/{sha}.json'
                row['prior_reason'] = r4.get('reason')
            elif c['input_key'] is None:
                row['action'] = 'unresolved_input'
            else:
                row['action'] = 'convert'
                if c.get('disk12_ifc'):
                    row['retry_of'] = c['disk12_ifc'][0]['result_key']     # Disk-1/2 converter differs (older kernel ladder)
                ifc_jobs.append({'id': sha, 'sha256': sha, 'size': c['size'], 'kind': kind, 'input_key': c['input_key'], 'input_from': c['input_from'],
                                 'n_paths': len(c['occ']), 'paths': occ_paths(c), 'retry_of': row.get('retry_of')})
            cnt[row['action']] += 1
            g.write(json.dumps(row) + '\n')
    summ['ifc'] = {'distinct': len(IFC), 'raw_files': sum(len(c['occ']) for c in IFC.values()), 'actions': dict(cnt),
                   'by_kind': dict(collections.Counter(ext_of(c['occ'][0][2]) for c in IFC.values())),
                   'input_from': dict(collections.Counter(c['input_from'] for c in IFC.values()))}

    # DB1
    cnt = collections.Counter()
    with gzip.open(os.path.join(W, 'out', 'contents_db1.jsonl.gz'), 'wt') as g:
        for sha, c in sorted(DB1.items()):
            row = {'pipeline': 'db1', 'id': sha, 'sha256': sha, 'size': c['size'], 'n_paths': len(c['occ']), 'paths': occ_paths(c),
                   'input_key': c['input_key'], 'input_from': c['input_from'], 'xslib': c['xslib'],
                   'siblings': [s[0] for s in (c.get('siblings') or [])][:200],
                   'prior': any(k.startswith('prior:') for k in c['keys'])}
            if c['xslib']:
                row['action'] = 'excluded_xslib'
            elif c['size'] == 0:
                row['action'] = 'empty_file'
            else:
                reuse = None
                r4, r12, rw = c.get('data4_db1'), c.get('disk12_db1'), c.get('disk12_windows')
                if ok_result(r4):
                    reuse = {'from': 'data-4', 'step_key': r4.get('out_key'), 'result_key': f'{Z4}/_state/conv/db1/results/{sha}.json'}
                elif ok_result(r12):
                    reuse = {'from': 'disk-1/2', 'step_key': r12.get('out_key') or f'{D12}/conversions/db1-step/{sha}.stp', 'result_key': f'{D12}/_state/db1-v2/results/{sha}.json'}
                elif rw and str(rw.get('status', '')).upper() == 'OK':
                    reuse = {'from': 'disk-1/2-windows', 'step_key': None, 'result_key': f'{D12}/derived/db1-step/Disk-1/by-sha256/{sha}/result.json'}
                row['reuse'] = reuse
                if reuse:
                    row['action'] = 'reuse'
                    grade_jobs.append({'id': 'db1-' + sha, 'pipeline': 'db1', 'sha256': sha, 'size': c['size'], 'input_key': c['input_key'],
                                       'step_key': reuse['step_key'], 'result_key': reuse['result_key'], 'reuse_from': reuse['from'],
                                       'n_paths': len(c['occ']), 'paths': occ_paths(c, 5)})
                elif r4 or r12:
                    rr = r4 or r12
                    row['action'] = 'failed_before_same_converter'; row['prior_reason'] = rr.get('reason') or rr.get('status')
                    row['prior_result_key'] = (f'{Z4}/_state/conv/db1/results/{sha}.json' if r4 else f'{D12}/_state/db1-v2/results/{sha}.json')
                elif c['input_key'] is None:
                    row['action'] = 'unresolved_input'
                else:
                    row['action'] = 'convert'
                    db1_jobs.append({'id': sha, 'sha256': sha, 'size': c['size'], 'input_key': c['input_key'], 'input_from': c['input_from'],
                                     'n_paths': len(c['occ']), 'paths': occ_paths(c), 'siblings': row['siblings'][:100]})
            cnt[row['action']] += 1
            g.write(json.dumps(row) + '\n')
    summ['db1'] = {'distinct': len(DB1), 'raw_files': sum(len(c['occ']) for c in DB1.values()), 'actions': dict(cnt),
                   'input_from': dict(collections.Counter(c['input_from'] for c in DB1.values()))}

    # SDS2
    cnt = collections.Counter()
    with gzip.open(os.path.join(W, 'out', 'contents_sds2.jsonl.gz'), 'wt') as g:
        for fpc, c in sorted(SDS.items()):
            jid = fpc[:24]; fp = fpc
            row = {'pipeline': 'sds2', 'id': jid, 'fpc': fpc, 'rep_folder_fp': c['fp'], 'full_folder_fps': len(c['full_fps']),
                   'jsetup_sha256': c['jsetup'], 'n_model_files': c['n_model'], 'model_bytes': c['model_bytes'],
                   'n_paths': len(c['occ']), 'paths': occ_paths(c), 'unresolved_files': c.get('unresolved'), 'resolved_from': c.get('resolved_from'),
                   'files_key': f'{ST}/sds2/files/{fpc}.json.gz', 'complete_layout': c['has_job_mtrl'] and c['has_mem_idx']}
            reuse = None
            for m in c.get('data4_sds2') or []:
                r = m.get('result') or {}
                if r.get('status') == 'ok':
                    reuse = {'from': 'data-4', 'step_key': (r.get('step') or {}).get('key'), 'result_key': f'{Z4}/_state/conv/sds2/results/{m["id"]}.json',
                             'prefix': (r.get('outputs') or {}).get('prefix')}
                    break
            if not reuse:
                for m in c.get('disk2_run2') or []:
                    for x in m['rows']:
                        s2 = x.get('stage2') or {}
                        if x.get('status') == 'ok' and s2.get('rc') == 0 and x.get('qa') != 'fail' and s2.get('solids') and s2.get('valid') == s2.get('solids'):
                            pre = x['s3'].replace('s3://annotationprod/', '').replace('s3://bim-proprietary-data/', '')
                            reuse = {'from': 'disk-2-run-2', 'step_key': pre.rstrip('/') + '/' + x['name'] + '_stage2.step', 'prefix': pre, 'row': x,
                                     'identity': m['identity']}
                            break
                    if reuse:
                        break
            row['reuse'] = reuse
            if reuse:
                row['action'] = 'reuse'
                grade_jobs.append({'id': 'sds2-' + jid, 'pipeline': 'sds2', 'fpc': fpc, 'step_key': reuse['step_key'], 'result_key': reuse.get('result_key'),
                                   'prefix': reuse.get('prefix'), 'reuse_from': reuse['from'], 'run2_row': reuse.get('row'), 'n_paths': len(c['occ']),
                                   'paths': occ_paths(c, 5)})
            else:
                row['action'] = 'convert'
                prev = [m.get('result') for m in c.get('data4_sds2') or []] + [x for m in c.get('disk2_run2') or [] for x in m['rows']]
                if prev:
                    row['failed_before'] = [{'status': p.get('status'), 'reason': p.get('reason') or p.get('qa_reasons')} for p in prev if p][:3]
                occ0 = c.get('rep_occ') or c['occ'][0]
                sds_jobs.append({'id': jid, 'fpc': fpc, 'name': (occ0[2].rstrip('/').rsplit('/', 1)[-1] or occ0[1].rsplit('/', 1)[-1]),
                                 'model_bytes': c['model_bytes'], 'size': c['model_bytes'], 'n_files': c['n_model'], 'files_key': row['files_key'],
                                 'unresolved_files': c.get('unresolved'), 'jsetup_sha256': c['jsetup'], 'complete_layout': row['complete_layout'],
                                 'archive': occ0[1], 'job_root': occ0[2], 'n_paths': len(c['occ']), 'paths': occ_paths(c),
                                 'failed_before': row.get('failed_before')})
            cnt[row['action']] += 1
            g.write(json.dumps(row) + '\n')
    summ['sds2'] = {'distinct_converter_inputs': len(SDS), 'distinct_full_folders': sum(len(c['full_fps']) for c in SDS.values()),
                    'distinct_jsetup': len({c['jsetup'] for c in SDS.values()}),
                    'raw_job_folders': sum(len(c['occ']) for c in SDS.values()), 'actions': dict(cnt),
                    'jobs_with_unresolved_files': sum(1 for c in SDS.values() if c.get('unresolved')),
                    'incomplete_layout': sum(1 for c in SDS.values() if not (c['has_job_mtrl'] and c['has_mem_idx']))}
    ifc_jobs.sort(key=lambda j: -(j['size'] or 0)); db1_jobs.sort(key=lambda j: -(j['size'] or 0)); sds_jobs.sort(key=lambda j: -(j['size'] or 0))
    for name in ('contents_ifc', 'contents_db1', 'contents_sds2'):
        put_file(f'{ST}/scan/{name}.jsonl.gz', os.path.join(W, 'out', name + '.jsonl.gz'))
    put_json(f'{ST}/ifc/jobs.json', ifc_jobs); put_json(f'{ST}/db1/jobs.json', db1_jobs); put_json(f'{ST}/sds2/jobs.json', sds_jobs)
    put_json(f'{ST}/grade/jobs.json', grade_jobs)
    summ['jobs'] = {'ifc': len(ifc_jobs), 'db1': len(db1_jobs), 'sds2': len(sds_jobs), 'grade': len(grade_jobs)}
    summ['jobs_bytes'] = {'ifc': sum(j['size'] or 0 for j in ifc_jobs), 'db1': sum(j['size'] or 0 for j in db1_jobs),
                          'sds2': sum(j['size'] or 0 for j in sds_jobs)}
    put_json(f'{ST}/scan/summary.json', summ)
    json.dump(summ, open(os.path.join(W, 'out', 'summary.json'), 'w'), indent=1)
    log('SUMMARY', json.dumps(summ))


def main():
    phases = sys.argv[1:] or ['a', 'b']
    os.makedirs(W, exist_ok=True)
    jobs = json.loads(s3().get_object(Bucket=CB, Key=JOBS_KEY)['Body'].read())
    log(f'{len(jobs)} data-3 jobs; procs={NPROC}')
    if 'a' in phases:
        errs = phase_a(jobs)
        if errs:
            log('phase A had errors; re-run to retry'); sys.exit(2)
        # upload parts for the record (small)
        os.system(f'cd {W} && tar czf parts.tgz parts')
        put_file(f'{ST}/scan/parts.tgz', os.path.join(W, 'parts.tgz'))
    if 'b' in phases:
        phase_b(jobs)


if __name__ == '__main__':
    main()
