#!/bin/bash
# READ-ONLY audit: every package in dataset/main/{3d,2d} (earlier projpkg4 deliverable) and dataset/packages/{3d,3d_partial} (Zenitude):
# project.json + manifest.jsonl present, path layout (flat <top>/<channel>/<file>), channel vocabulary, field sets, sha overlaps.
# Runs detached; result /opt/report/out/pkg_audit.json (+ .done). GET/LIST only.
mkdir -p /opt/report/out /opt/report/work
cat > /opt/report/work/pkg_audit.py <<'PY'
import json, re, collections, boto3, time, sys
from multiprocessing import Pool
B = 'bim-proprietary-data'; D = 'cad-disk-extract/dataset/'
ROOTS = ['main/3d', 'main/2d', 'packages/3d', 'packages/3d_partial']
def s3c():
    return boto3.client('s3', region_name='ap-south-1')
def list_projects(root):
    s3 = s3c(); out = []; tok = None
    while True:
        kw = dict(Bucket=B, Prefix=D + root + '/', Delimiter='/', MaxKeys=1000)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [c['Prefix'][len(D + root + '/'):-1] for c in r.get('CommonPrefixes') or []]
        stray = [o['Key'] for o in r.get('Contents') or []]
        if stray: out += ['__STRAY__' + k for k in stray]
        if not r.get('IsTruncated'): break
        tok = r['NextContinuationToken']
    return out
HEX6 = re.compile(r'-[0-9a-f]{6}(\.[^./]+)?$')
def one(args):
    root, pid = args
    s3 = s3c(); res = {'root': root, 'pid': pid, 'err': None}
    if pid.startswith('__STRAY__'): res['err'] = 'stray_object_at_root'; return res
    base = D + root + '/' + pid + '/'
    # top level of the package (one LIST with delimiter)
    r = s3.list_objects_v2(Bucket=B, Prefix=base, Delimiter='/')
    res['top_files'] = sorted(o['Key'][len(base):] for o in r.get('Contents') or [])
    res['top_dirs'] = sorted(c['Prefix'][len(base):-1] for c in r.get('CommonPrefixes') or [])
    try:
        pj = json.loads(s3.get_object(Bucket=B, Key=base + 'project.json')['Body'].read())
    except Exception as e:
        res['err'] = 'no_project_json:' + type(e).__name__; return res
    res['pj_keys'] = sorted(pj.keys())
    res['pj'] = {k: pj.get(k) for k in ('format', 'schema', 'version', 'route', 'tier', 'id', 'status', 'pkg_version', 'packager') if k in pj}
    res['addon_of'] = pj.get('addon_of')
    try:
        body = s3.get_object(Bucket=B, Key=base + 'manifest.jsonl')['Body'].read().decode('utf-8')
    except Exception as e:
        res['err'] = 'no_manifest:' + type(e).__name__; return res
    rowkeys = collections.Counter(); chans = collections.Counter(); depth = collections.Counter(); bad = []
    hexn = 0; n = 0; shas = []; step_class = collections.Counter(); pk = collections.Counter(); nosha = 0
    for line in body.split('\n'):
        if not line.strip(): continue
        row = json.loads(line); n += 1
        rowkeys[tuple(sorted(row.keys()))] += 1
        rp = row.get('relpath') or row.get('path') or ''
        parts = rp.split('/'); depth[len(parts)] += 1
        ch = '/'.join(parts[:2]) if len(parts) >= 3 else ('(root)' if len(parts) == 1 else parts[0])
        chans[ch] += 1
        if len(parts) != 3 and len(bad) < 5: bad.append(rp)
        if HEX6.search(parts[-1]): hexn += 1
        sh = row.get('sha256')
        if sh: shas.append(int(sh[:15], 16))
        else: nosha += 1
        if ch == 'model/step':
            step_class[str(row.get('class'))] += 1
            p_ = row.get('partial')
            if p_: pk[str(p_.get('kind'))] += 1
    res.update(n=n, rowkeys={'|'.join(k): v for k, v in rowkeys.items()}, chans=dict(chans), depth=dict(depth), bad_paths=bad, hex6=hexn,
               nosha=nosha, step_class=dict(step_class), partial_kind=dict(pk), pid_len=len(pid), shas=shas)
    return res
if __name__ == '__main__':
    t0 = time.time(); jobs = []
    for root in ROOTS:
        ps = list_projects(root); jobs += [(root, p) for p in ps]; print(root, len(ps), flush=True)
    with Pool(48) as pool:
        res = list(pool.imap_unordered(one, jobs, chunksize=4))
    print('read', len(res), 'packages in', round(time.time() - t0), 's', flush=True)
    out = {'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'roots': {}}
    byroot = collections.defaultdict(list)
    for r in res: byroot[r['root']].append(r)
    shaset = {}; shaproj = {}
    for root, L in byroot.items():
        A = {'projects': len(L), 'errors': collections.Counter(), 'top_files': collections.Counter(), 'top_dirs': collections.Counter(),
             'pj_keys': collections.Counter(), 'pj_vals': collections.Counter(), 'rowkeys': collections.Counter(), 'chans': collections.Counter(),
             'chan_projects': collections.Counter(), 'depth': collections.Counter(), 'bad_paths': [], 'rows': 0, 'hex6': 0, 'nosha': 0,
             'step_class': collections.Counter(), 'partial_kind': collections.Counter(), 'pid_len_max': 0, 'addons': 0, 'example_pids': []}
        allsh = collections.Counter()
        for r in L:
            if r.get('err'): A['errors'][r['err']] += 1; continue
            A['top_files'][','.join(r['top_files'])] += 1; A['top_dirs'][','.join(r['top_dirs'])] += 1
            for k in r['pj_keys']: A['pj_keys'][k] += 1
            for k, v in r['pj'].items():
                if k in ('format', 'schema', 'version', 'route', 'tier', 'status', 'pkg_version', 'packager'): A['pj_vals'][f'{k}={v}'] += 1
            for k, v in r['rowkeys'].items(): A['rowkeys'][k] += v
            for k, v in r['chans'].items(): A['chans'][k] += v; A['chan_projects'][k] += 1
            for k, v in r['depth'].items(): A['depth'][str(k)] += v
            A['bad_paths'] += [r['pid'][:80] + ' :: ' + b for b in r['bad_paths']][:3]
            A['rows'] += r['n']; A['hex6'] += r['hex6']; A['nosha'] += r['nosha']
            for k, v in r['step_class'].items(): A['step_class'][k] += v
            for k, v in r['partial_kind'].items(): A['partial_kind'][k] += v
            A['pid_len_max'] = max(A['pid_len_max'], r['pid_len']); A['addons'] += bool(r.get('addon_of'))
            if len(A['example_pids']) < 3: A['example_pids'].append(r['pid'])
            for s in set(r['shas']): allsh[s] += 1
        A['distinct_sha'] = len(allsh); A['sha_in_2plus_projects'] = sum(1 for v in allsh.values() if v > 1)
        A['bad_paths'] = A['bad_paths'][:12]
        shaset[root] = set(allsh)
        out['roots'][root] = {k: (dict(v.most_common()) if isinstance(v, collections.Counter) else v) for k, v in A.items()}
    # add-on dedup: no add-on file content inside the perfect package it extends
    perf = {r['pid']: set(r.get('shas') or []) for r in byroot['packages/3d'] if not r.get('err')}
    ov = collections.Counter(); missing_target = 0
    for r in byroot['packages/3d_partial']:
        if r.get('err') or not r.get('addon_of'): continue
        tgt = str(r['addon_of']).rstrip('/').split('/')[-1]
        if tgt not in perf: missing_target += 1; continue
        ov['addons_checked'] += 1; k = len(set(r['shas']) & perf[tgt]); ov['files_also_in_target'] += k; ov['addons_with_overlap'] += bool(k)
    out['addon_dedup'] = dict(ov); out['addon_dedup']['addon_target_not_found'] = missing_target
    R = list(shaset)
    out['cross_root_sha_overlap'] = {f'{a} & {b}': len(shaset[a] & shaset[b]) for i, a in enumerate(R) for b in R[i + 1:]}
    json.dump(out, open('/opt/report/out/pkg_audit.json', 'w'), indent=1)
    print('DONE', round(time.time() - t0), 's', flush=True)
PY
cd /opt/report/work && setsid nohup /opt/report/venv/bin/python pkg_audit.py > /opt/report/out/pkg_audit.log 2>&1 < /dev/null &
sleep 2; echo LAUNCHED; head -3 /opt/report/out/pkg_audit.log
