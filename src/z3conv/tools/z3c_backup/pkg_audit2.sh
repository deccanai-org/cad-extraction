#!/bin/bash
# READ-ONLY deep-dive: cross-project duplicate content per root and channel (sha for packages/*, etag+bytes proxy for all roots),
# add-on files already in their perfect package, partial STEP manifest rows vs files. Result /opt/report/out/pkg_audit2.json
cat > /opt/report/work/pkg_audit2.py <<'PY'
import json, collections, boto3, time
from multiprocessing import Pool
B = 'bim-proprietary-data'; D = 'cad-disk-extract/dataset/'
ROOTS = ['main/3d', 'main/2d', 'packages/3d', 'packages/3d_partial']
def s3c(): return boto3.client('s3', region_name='ap-south-1')
def list_projects(root):
    s3 = s3c(); out = []; tok = None
    while True:
        kw = dict(Bucket=B, Prefix=D + root + '/', Delimiter='/', MaxKeys=1000)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw); out += [c['Prefix'][len(D + root + '/'):-1] for c in r.get('CommonPrefixes') or []]
        if not r.get('IsTruncated'): break
        tok = r['NextContinuationToken']
    return out
def one(a):
    root, pid = a; s3 = s3c(); base = D + root + '/' + pid + '/'
    try: body = s3.get_object(Bucket=B, Key=base + 'manifest.jsonl')['Body'].read().decode()
    except Exception: return root, pid, None, None, []
    try: pj = json.loads(s3.get_object(Bucket=B, Key=base + 'project.json')['Body'].read())
    except Exception: pj = {}
    rows = []
    for l in body.split('\n'):
        if not l.strip(): continue
        r = json.loads(l); rp = r.get('relpath') or ''
        ch = '/'.join(rp.split('/')[:2])
        rows.append((ch, rp, (r.get('sha256') or '')[:16], f"{(r.get('etag') or '').strip(chr(34))}:{r.get('bytes')}", r.get('model_id'), r.get('class'),
                     (r.get('partial') or {}).get('kind') if isinstance(r.get('partial'), dict) else None))
    return root, pid, pj.get('addon_of'), pj.get('model_step_by_source'), rows
if __name__ == '__main__':
    t0 = time.time(); jobs = [(r, p) for r in ROOTS for p in list_projects(r)]
    with Pool(48) as pool: res = list(pool.imap_unordered(one, jobs, chunksize=4))
    out = {'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    by = collections.defaultdict(list)
    for x in res: by[x[0]].append(x)
    dup = {}
    for root, L in by.items():
        for keyname, ki in (('sha', 2), ('etag_bytes', 3)):
            cnt = collections.defaultdict(set); chan = {}
            for _, pid, _, _, rows in L:
                for r in rows or []:
                    k = r[ki]
                    if not k or k.startswith(':') or k.endswith(':None'): continue
                    cnt[k].add(pid); chan.setdefault(k, r[0])
            if not cnt: continue
            multi = {k: len(v) for k, v in cnt.items() if len(v) > 1}
            bych = collections.Counter(); extra = collections.Counter()
            for k, n in multi.items(): bych[chan[k]] += 1; extra[chan[k]] += n - 1
            projs = set()
            for k in multi: projs |= cnt[k]
            dup[f'{root}|{keyname}'] = {'distinct': len(cnt), 'in_2plus_projects': len(multi), 'extra_copies': sum(n - 1 for n in multi.values()),
                                        'projects_sharing_any': len(projs), 'by_channel_contents': dict(bych.most_common()), 'by_channel_extra_copies': dict(extra.most_common()),
                                        'max_projects_one_content': max(multi.values()) if multi else 0}
    out['dup'] = dup
    # add-on files whose content is already in the perfect package they extend
    perf = {pid: {r[2]: r[1] for r in rows or [] if r[2]} for _, pid, _, _, rows in by['packages/3d']}
    ov = []
    for _, pid, addon, _, rows in by['packages/3d_partial']:
        if not addon: continue
        t = str(addon).rstrip('/').split('/')[-1]; P = perf.get(t, {})
        for r in rows or []:
            if r[2] and r[2] in P: ov.append({'addon': pid, 'file': r[1], 'channel': r[0], 'in_perfect_as': P[r[2]], 'class': r[5], 'kind': r[6]})
    out['addon_overlap'] = ov
    # STEP rows vs distinct STEP models/contents per tier
    for root in ('packages/3d', 'packages/3d_partial'):
        rows = [(pid, r) for _, pid, _, _, R in by[root] for r in R or [] if r[0] == 'model/step']
        mids = collections.Counter(r[4] for _, r in rows); shas = collections.Counter(r[2] for _, r in rows)
        out[f'step|{root}'] = {'rows': len(rows), 'distinct_model_id': len(mids), 'rows_without_model_id': mids.get(None, 0),
                               'distinct_sha': len(shas), 'model_id_in_2plus_rows': sum(1 for k, v in mids.items() if k and v > 1),
                               'examples_no_model_id': [(pid[:90], r[1], r[5], r[6]) for pid, r in rows if not r[4]][:12],
                               'examples_dup_model_id': [(pid[:90], r[1]) for pid, r in rows if r[4] and mids[r[4]] > 1][:12]}
    # cross-tier: packages/3d vs packages/3d_partial by channel, split add-on / partial-only
    psha = collections.defaultdict(set)
    for _, pid, _, _, rows in by['packages/3d']:
        for r in rows or []: psha[r[2]].add(pid)
    ct = collections.Counter(); ctp = collections.Counter()
    for _, pid, addon, _, rows in by['packages/3d_partial']:
        for r in rows or []:
            if r[2] in psha: ct[('add-on' if addon else 'partial-only', r[0])] += 1; ctp['add-on' if addon else 'partial-only'] += 1
    out['cross_tier_rows'] = {f'{a}|{c}': v for (a, c), v in ct.most_common()}; out['cross_tier_rows_total'] = dict(ctp)
    json.dump(out, open('/opt/report/out/pkg_audit2.json', 'w'), indent=1)
    print('DONE', round(time.time() - t0), 's', flush=True)
PY
cd /opt/report/work && setsid nohup /opt/report/venv/bin/python pkg_audit2.py > /opt/report/out/pkg_audit2.log 2>&1 < /dev/null &
sleep 1; echo LAUNCHED
