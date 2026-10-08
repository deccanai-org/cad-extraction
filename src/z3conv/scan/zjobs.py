#!/usr/bin/env python3
"""Multi-disk job builder (phase 2, after zcensus.py on the same box / work dir).

  python3 zjobs.py <disk>

Reads the census manifest-pass parts (local work dir, else <root>/_state/conv2/scan/parts.tgz), the conversion indexes of the
earlier disks (reuse by sha: a content converted - or queued - on current code anywhere is never queued again) and resolves the
input object of every NEW content:
  this disk's real object > this disk's dedup marker (<root>/_state/sha/..) > loose source (src:) > a Disk-1/2 copy
  (pkg-resolver disk12_sha_map, size-checked; DB1 also the Disk-1/2 db1_jobs list) > unresolved (reported, not queued)
SDS2: the representative folder of each new converter input (fewest unresolved files); its model files resolved the same way
(<root>/_state/conv2/sds2/files/<fpc>.json.gz). All revisions are queued (as in data-3); the primary per jsetup is decided by the
index builder across disks.
Writes only <root>/_state/conv2/: scan/contents_{ifc,db1,sds2}.jsonl.gz (every distinct content: action reuse/convert/...,
reuse_from), <pipe>/jobs.json (largest first, the data-3 job schema), sds2/files/, scan/jobs_summary.json.
"""
import os, sys, json, gzip, time, collections, subprocess, tarfile
from concurrent.futures import ThreadPoolExecutor
import zcensus as zc

DISK = zc.DISK; ROOT = zc.ROOT; W = zc.W; B = zc.B
ST2 = f'{ROOT}/_state/conv2'
D12 = 'cad-disk-extract'
D12MAP = ('annotationprod', 'cad-disk-extract/agentwork/pkg-resolver/disk12_sha_map.jsonl.gz')
log = zc.log; s3 = zc.s3; getj = zc.getj; ext_of = zc.ext_of


def put(key, body, gz=False):
    assert key.startswith(ST2 + '/'), key                     # the builder writes only this disk's conv2 state
    if gz:
        body = gzip.compress(body, 6)
    s3().put_object(Bucket=B, Key=key, Body=body)


def text(key):
    try:
        return s3().get_object(Bucket=B, Key=key)['Body'].read().decode().strip()
    except Exception:
        return None


def marker(sha):
    t = text(f'{ROOT}/_state/sha/{sha[:2]}/{sha}')
    return t if t and t.startswith('cad-disk-extract/') else None


def main():
    if not os.path.isdir(os.path.join(W, 'parts')) or not os.listdir(os.path.join(W, 'parts')):
        os.makedirs(W, exist_ok=True)
        s3().download_file(B, f'{zc.OUT}/parts.tgz', os.path.join(W, 'parts.tgz'))
        with tarfile.open(os.path.join(W, 'parts.tgz')) as t:
            t.extractall(W)
    jl_ = getj(f'{ROOT}/_control/jobs.json') or []
    arch = {j['id']: (j.get('key') or j.get('dir') or j['id']) for j in jl_ if isinstance(j, dict) and j.get('id')}
    IFC, DB1, SDS = {}, {}, {}
    for fn in sorted(os.listdir(os.path.join(W, 'parts'))):
        d = json.load(gzip.open(os.path.join(W, 'parts', fn), 'rt'))
        a = arch.get(d['id'], d['id'])
        for p, size, sha, k in d['ifc']:
            c = IFC.setdefault(sha, {'sha256': sha, 'size': size, 'occ': [], 'keys': set()})
            c['occ'].append((a, p)); c['keys'].add(k)
        for p, size, sha, k in d['db1']:
            c = DB1.setdefault(sha, {'sha256': sha, 'size': size, 'occ': [], 'keys': set(), 'xslib': True})
            c['occ'].append((a, p)); c['keys'].add(k)
            if p[p.rfind('/') + 1:].lower() != 'xslib.db1':
                c['xslib'] = False
        for r in d['sds2']:
            c = SDS.setdefault(r['fpc'], {'fpc': r['fpc'], 'occ': [], 'reps': []})
            c['occ'].append((a, r['root'])); c['reps'].append(r)
    log(f'{DISK}: IFC {len(IFC)}, DB1 {len(DB1)}, SDS2 {len(SDS)} distinct')

    # ---- reuse sets (earlier disks, current converters)
    idx = {'ifc': {}, 'db1': {}, 'sds2': {}}; queued = {'ifc': {}, 'db1': {}, 'sds2': {}}
    for dname, st in zc.CFG['reuse_from']:
        raw = s3().get_object(Bucket=B, Key=f'{st}/index.jsonl.gz')['Body'].read()
        for l in gzip.decompress(raw).decode().splitlines():
            if l.strip():
                r = json.loads(l)
                if r.get('pipeline') in idx:
                    idx[r['pipeline']].setdefault(r['id'], {'disk': dname, 'class': r.get('class'), 'step_key': r.get('step_key')})
        for p in ('ifc', 'db1', 'sds2'):
            for j in (getj(f'{st}/{p}/jobs.json') or []) + (getj(f'{st}/{p}/jobs_reconvert.json') or []):
                if isinstance(j, dict) and j.get('id'):
                    queued[p].setdefault(j['id'], dname)

    # ---- Disk-1/2 lookups
    d12 = {}
    try:
        raw = s3().get_object(Bucket=D12MAP[0], Key=D12MAP[1])['Body'].read()
        for l in gzip.decompress(raw).decode().splitlines():
            if l.strip():
                r = json.loads(l)
                if r.get('proof') == 's3_sha256' and str(r.get('key', '')).startswith('cad-disk-extract/'):
                    d12[r['sha256']] = (r['key'], int(r['bytes']))
    except Exception as e:
        log('disk12_sha_map unavailable:', e)
    d12db1 = {j['sha']: j['key'] for j in (getj(f'{D12}/_control/db1-v2/db1_jobs.json') or {}).get('jobs', []) if j.get('sha') and j.get('key')}
    log(f'disk12 map {len(d12)}, db1_jobs {len(d12db1)}')

    def resolve(c, pipe):
        keys = c['keys']; sha = c['sha256']
        real = sorted(k for k in keys if k.startswith(ROOT + '/'))
        if real:
            return real[0], 'disk_real'
        src = sorted(k[4:] for k in keys if k.startswith('src:'))
        if src:
            return src[0], 'disk_source'
        if any(k.startswith('sha256:') for k in keys):
            t = marker(sha)
            if t:
                return t, 'disk_marker'
        if sha in d12 and d12[sha][1] == c['size']:
            return d12[sha][0], 'disk12_map'
        if pipe == 'db1' and sha in d12db1:
            return d12db1[sha], 'disk12_db1_jobs'
        return None, 'unresolved'

    def action(pipe, cid):
        # 'reuse_disk': converted on current code on an earlier disk (the index builder copies that row); 'reuse_disk_queued': queued
        # there, not finished yet (copied once it is). Distinct from data-3's 'reuse' (older conversion re-graded).
        if cid in idx[pipe]:
            return 'reuse_disk', idx[pipe][cid]['disk']
        if cid in queued[pipe]:
            return 'reuse_disk_queued', queued[pipe][cid]
        return 'convert', None

    summ = {'disk': DISK, 'updated': zc.now()}
    jobs = {'ifc': [], 'db1': [], 'sds2': []}
    for pipe, D in (('ifc', IFC), ('db1', DB1)):
        cnt = collections.Counter(); how = collections.Counter(); rows = []
        todo = []
        for sha, c in sorted(D.items()):
            row = {'pipeline': pipe, 'id': sha, 'sha256': sha, 'size': c['size'], 'n_paths': len(c['occ']),
                   'paths': [f'{a} :: {p}' for a, p in c['occ'][:20]]}
            if pipe == 'ifc':
                row['kind'] = ext_of(c['occ'][0][1])
            if pipe == 'db1' and c['xslib']:
                row['action'] = 'excluded_xslib'
            elif c['size'] == 0:
                row['action'] = 'empty_file'
            else:
                act, frm = action(pipe, sha)
                row['action'] = act
                if frm:
                    row['reuse_from'] = frm
                if act == 'convert':
                    todo.append((row, c))
            rows.append(row)
        with ThreadPoolExecutor(64) as ex:
            for (row, c), (k, h) in zip(todo, ex.map(lambda rc: resolve(rc[1], pipe), todo)):
                row['input_key'] = k; row['input_from'] = h; how[h] += 1
                if k is None:
                    row['action'] = 'unresolved_input'
                else:
                    j = {'id': row['id'], 'sha256': row['id'], 'size': row['size'], 'input_key': k, 'input_from': h,
                         'n_paths': row['n_paths'], 'paths': row['paths'], 'disk': DISK}
                    if pipe == 'ifc':
                        j['kind'] = row['kind']; j['retry_of'] = None
                    jobs[pipe].append(j)
        for row in rows:
            cnt[row['action']] += 1
        put(f'{ST2}/scan/contents_{pipe}.jsonl.gz', ''.join(json.dumps(r) + '\n' for r in rows).encode(), gz=True)
        summ[pipe] = {'distinct': len(D), 'actions': dict(cnt), 'input_from': dict(how),
                      'reuse_from': dict(collections.Counter(r.get('reuse_from') for r in rows if r.get('reuse_from'))),
                      'jobs': len(jobs[pipe]), 'jobs_GB': round(sum(j['size'] for j in jobs[pipe]) / 1e9, 1)}

    # ---- SDS2
    cnt = collections.Counter(); how = collections.Counter(); rows = []

    def sds_files(c):
        best = None
        for r in sorted(c['reps'], key=lambda r: (sum(v for k, v in r['kinds'].items() if k in ('disk12', 'none')), -r['n_model'])):
            fl = json.load(gzip.open(os.path.join(W, 'roots', r['fp'] + '.json.gz'), 'rt'))
            out = []; unres = 0; kinds = collections.Counter()
            for rel, size, sha, key in fl:
                if key.startswith(ROOT + '/'):
                    k, h = key, 'disk_real'
                elif key.startswith('src:'):
                    k, h = key[4:], 'disk_source'
                elif key.startswith('sha256:'):
                    k, h = marker(sha), 'disk_marker'
                elif sha in d12 and d12[sha][1] == size:
                    k, h = d12[sha][0], 'disk12_map'
                else:
                    k, h = None, 'unresolved'
                if size == 0 and not k:
                    k, h = '', 'empty'
                if k is None:
                    unres += 1; h = 'unresolved'
                kinds[h] += 1
                out.append({'p': rel, 'sha256': sha, 'size': size, 'key': k})
            if best is None or unres < best[1]:
                best = (r, unres, kinds, out)
            if unres == 0:
                break
        return best
    todo = []
    for fpc, c in sorted(SDS.items()):
        jid = fpc[:24]
        r0 = max(c['reps'], key=lambda r: r['n_model'])
        row = {'pipeline': 'sds2', 'id': jid, 'fpc': fpc, 'jsetup_sha256': r0.get('jsetup'), 'n_model_files': r0['n_model'],
               'model_bytes': r0['model_bytes'], 'n_paths': len(c['occ']), 'paths': [f'{a} :: {p}' for a, p in c['occ'][:20]],
               'complete_layout': any(r['complete'] for r in c['reps'])}
        act, frm = action('sds2', jid)
        row['action'] = act
        if frm:
            row['reuse_from'] = frm
        if act == 'convert':
            todo.append((row, c))
        rows.append(row)
    with ThreadPoolExecutor(16) as ex:
        for (row, c), best in zip(todo, ex.map(lambda rc: sds_files(rc[1]), todo)):
            r, unres, kinds, out = best
            key = f'{ST2}/sds2/files/{row["fpc"]}.json.gz'
            put(key, json.dumps(out).encode(), gz=True)
            row.update(files_key=key, unresolved_files=unres, resolved_from=dict(kinds))
            how['complete' if not unres else 'with_unresolved_files'] += 1
            a_, root_ = next(((a, p) for a, p in c['occ'] if p == r['root']), c['occ'][0])
            jobs['sds2'].append({'id': row['id'], 'fpc': row['fpc'], 'name': (root_.rstrip('/').rsplit('/', 1)[-1] or a_.rsplit('/', 1)[-1]),
                                 'model_bytes': r['model_bytes'], 'size': r['model_bytes'], 'n_files': r['n_model'], 'files_key': key,
                                 'unresolved_files': unres, 'jsetup_sha256': r.get('jsetup'), 'complete_layout': row['complete_layout'],
                                 'archive': a_, 'job_root': root_, 'n_paths': row['n_paths'], 'paths': row['paths'], 'disk': DISK})
    for row in rows:
        cnt[row['action']] += 1
    put(f'{ST2}/scan/contents_sds2.jsonl.gz', ''.join(json.dumps(r) + '\n' for r in rows).encode(), gz=True)
    summ['sds2'] = {'distinct': len(SDS), 'actions': dict(cnt), 'files': dict(how),
                    'reuse_from': dict(collections.Counter(r.get('reuse_from') for r in rows if r.get('reuse_from'))),
                    'jobs': len(jobs['sds2']), 'jobs_GB': round(sum(j['size'] for j in jobs['sds2']) / 1e9, 1)}
    for p in jobs:
        jobs[p].sort(key=lambda j: -(j.get('size') or 0))
        put(f'{ST2}/{p}/jobs.json', json.dumps(jobs[p]).encode())
    put(f'{ST2}/scan/jobs_summary.json', json.dumps(summ, indent=1).encode())
    log('JOBS', json.dumps(summ))


if __name__ == '__main__':
    main()
