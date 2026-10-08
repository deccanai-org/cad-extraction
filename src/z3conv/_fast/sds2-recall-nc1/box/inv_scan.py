#!/usr/bin/env python3
"""sds2-recall-nc1 inventory (runs on the agent box, never on the Mac).

  1. steps   : every data-3 SDS2 STEP output per job id and converter label (S3 listing of conversions/sds2-step/):
               root-level files = d3 fleet run with sds2-step-pipeline-v4-candidate (label v4c); <id>/v5.x/ = v5.x;
               _not_accepted/ kept apart; plus the reused v4c STEP of the 759 reuse jobs (contents_sds2 'reuse').
  2. nc1 d3  : NC1 / DSTV rows ('.nc1') of every data-3 archive manifest (_state/manifests/<id>.jsonl.gz)
  3. nc1 d4  : NC1 rows of every data-4 manifest (data-3 rows are 'prior:sha256:' = stored by data-4 / Disk-1/2)
  4. resolve : NC1 sha -> stored key (data-3 key / src: / data-3 marker / data-4 manifest row / data-4 marker)
Outputs: $W/inv/{steps.json,nc1_d3.jsonl.gz,nc1_d4.jsonl.gz,nc1_keys.json,inv_summary.json} (+ upload to RES)
usage: inv_scan.py [steps] [d3] [d4] [resolve]     (default: all)
"""
import os, sys, json, gzip, re, time, subprocess, collections, traceback
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'
CB = 'annotationprod'
D3 = 'cad-disk-extract/zenitude-data-3'
D4 = 'cad-disk-extract/zentitude-data-4'
RES = f'{D3}/_state/agentwork/sds2-recall-nc1'
W = os.environ.get('W', '/work/agentwork/sds2-recall-nc1')
INV = os.path.join(W, 'inv')
NTH = int(os.environ.get('NTH', '16'))
os.makedirs(INV, exist_ok=True)
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'},
                                                                            max_pool_connections=64))
    return _c['c']


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def lst(bucket, prefix):
    out = []
    for page in s3().get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        out += page.get('Contents', [])
    return out


def get_text(bucket, key):
    try:
        return s3().get_object(Bucket=bucket, Key=key)['Body'].read().decode('utf-8', 'replace').strip()
    except Exception:
        return None


def put(local, key):
    s3().upload_file(local, B, key)


STEP_RE = re.compile(r'^' + re.escape(D3) + r'/conversions/sds2-step/(_not_accepted/)?([0-9a-f]{24})/(?:(v[0-9][0-9.a-z]*)/)?([^/]+)$')


def phase_steps():
    t0 = time.time()
    objs = lst(B, f'{D3}/conversions/sds2-step/')
    steps = collections.defaultdict(dict)
    for o in objs:
        m = STEP_RE.match(o['Key'])
        if not m:
            continue
        na, jid, ver, fn = m.groups()
        lab = ver or 'v4c'
        if na:
            lab += '_not_accepted'
        e = steps[jid].setdefault(lab, {})
        if fn.endswith('_stage2.step'):
            e['step'] = o['Key']; e['step_size'] = o['Size']; e['stage'] = 2; e['mtime'] = o['LastModified'].isoformat()
        elif fn.endswith('_stage1.step') and e.get('stage') != 2:
            e['step'] = o['Key']; e['step_size'] = o['Size']; e['stage'] = 1; e['mtime'] = o['LastModified'].isoformat()
        elif fn.endswith('_stage2_manifest.json'):
            e['manifest'] = o['Key']
        elif fn.endswith('_stage2_pieces.csv'):
            e['pieces_csv'] = o['Key']
        elif fn == 'job.json':
            e['job_json'] = o['Key']
    # reused v4c (disk-2 run 2 / data-4) from contents_sds2
    tmp = os.path.join(INV, 'contents_sds2.jsonl.gz')
    s3().download_file(B, f'{D3}/_state/conv/scan/contents_sds2.jsonl.gz', tmp)
    nre = 0
    for line in gzip.open(tmp, 'rt'):
        r = json.loads(line)
        ru = r.get('reuse')
        if isinstance(ru, dict) and ru.get('step_key'):
            e = steps[r['id']].setdefault('v4c', {})
            if 'step' not in e:
                e.update({'step': ru['step_key'], 'stage': 2, 'reuse_from': ru.get('from'), 'result_key': ru.get('result_key')})
                nre += 1
    for jid, d in steps.items():
        for lab, e in list(d.items()):
            if 'step' not in e:
                d.pop(lab)
    steps = {k: v for k, v in steps.items() if v}
    json.dump(steps, open(os.path.join(INV, 'steps.json'), 'w'))
    c = collections.Counter(l for d in steps.values() for l in d)
    st = collections.Counter((l, e.get('stage')) for d in steps.values() for l, e in d.items())
    log(f'steps: {len(objs)} objects, {len(steps)} jobs with a STEP; labels {dict(c)}; reuse v4c {nre}; by stage {dict(st)} ({time.time() - t0:.0f}s)')
    put(os.path.join(INV, 'steps.json'), f'{RES}/inv/steps.json')
    return steps


PAT = r'\.(nc1|nc|dstv)", "size"'


def scan_one(bucket, key, outdir):
    mid = key.rsplit('/', 1)[-1].split('.')[0]
    out = os.path.join(outdir, mid + '.jsonl')
    if os.path.exists(out + '.done'):
        return mid, int(open(out + '.done').read() or 0)
    tmp = os.path.join(outdir, mid + '.gz')
    for attempt in range(4):
        try:
            s3().download_file(bucket, key, tmp); break
        except Exception:
            if attempt == 3:
                return mid, -1
            time.sleep(3)
    cmd = f"gzip -dc '{tmp}' | LC_ALL=C grep -iE '{PAT}' > '{out}'; echo ${{PIPESTATUS[0]}}"
    r = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    os.remove(tmp)
    n = sum(1 for _ in open(out))
    open(out + '.done', 'w').write(str(n))
    return mid, n


def phase_scan(tag, prefix, bucket=B):
    t0 = time.time()
    outdir = os.path.join(INV, 'scan_' + tag); os.makedirs(outdir, exist_ok=True)
    keys = [o['Key'] for o in lst(bucket, prefix) if o['Key'].endswith('.jsonl.gz')]
    log(f'{tag}: {len(keys)} manifests')
    tot = 0; bad = []; done = 0
    with ThreadPoolExecutor(NTH) as ex:
        for mid, n in ex.map(lambda k: scan_one(bucket, k, outdir), keys):
            done += 1
            if n < 0:
                bad.append(mid)
            else:
                tot += n
            if done % 500 == 0:
                log(f'{tag}: {done}/{len(keys)} manifests, {tot} rows, {len(bad)} failed ({time.time() - t0:.0f}s)')
    # merge
    outp = os.path.join(INV, f'nc1_{tag}.jsonl.gz')
    nrow = 0; ext = collections.Counter()
    with gzip.open(outp, 'wt') as g:
        for fn in sorted(os.listdir(outdir)):
            if not fn.endswith('.jsonl'):
                continue
            mid = fn[:-6]
            for line in open(os.path.join(outdir, fn), errors='replace'):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                p = r.get('path') or ''
                e = p.rsplit('.', 1)[-1].lower()
                ext[e] += 1
                g.write(json.dumps({'mid': mid, 'path': p, 'size': r.get('size'), 'sha256': r.get('sha256'), 'key': r.get('key'),
                                    'dedup': r.get('dedup')}) + '\n')
                nrow += 1
    log(f'{tag}: done {len(keys)} manifests, {nrow} rows by ext {dict(ext)}, failed {bad[:10]} ({time.time() - t0:.0f}s)')
    put(outp, f'{RES}/inv/nc1_{tag}.jsonl.gz')
    return nrow


def phase_resolve():
    t0 = time.time()
    d3 = [json.loads(l) for l in gzip.open(os.path.join(INV, 'nc1_d3.jsonl.gz'), 'rt')]
    d3 = [r for r in d3 if (r['path'] or '').lower().endswith('.nc1')]
    d4rows = collections.defaultdict(list)
    p4 = os.path.join(INV, 'nc1_d4.jsonl.gz')
    if os.path.exists(p4):
        for l in gzip.open(p4, 'rt'):
            r = json.loads(l)
            d4rows[r['sha256']].append(r)
    keys = {}; how = collections.Counter(); need4 = set(); need3 = set()
    for r in d3:
        sha = r['sha256']; k = r.get('key') or ''
        if sha in keys:
            continue
        if k.startswith(D3 + '/'):
            keys[sha] = k; how['data3'] += 1
        elif k.startswith('src:'):
            keys[sha] = k[4:]; how['data3_source'] += 1
        elif k.startswith('sha256:'):
            need3.add(sha)
        elif k.startswith('prior:') or k.startswith('disk12:'):
            got = None
            for x in d4rows.get(sha, []):
                kk = x.get('key') or ''
                if kk.startswith(D4 + '/'):
                    got = kk; break
            if got:
                keys[sha] = got; how['data4_manifest'] += 1
            else:
                need4.add(sha)
        elif (r.get('size') or 0) == 0:
            keys[sha] = ''; how['empty'] += 1
        else:
            how['unknown_key_form'] += 1
    log(f'resolve: {len(set(r["sha256"] for r in d3))} distinct NC1 shas; direct {dict(how)}; marker lookups d3 {len(need3)} d4 {len(need4)}')

    def mk(root, sha):
        t = get_text(B, f'{root}/_state/sha/{sha[:2]}/{sha}')
        return sha, (t if t and t.startswith('cad-disk-extract/') else None)
    with ThreadPoolExecutor(48) as ex:
        for sha, k in ex.map(lambda s: mk(D3, s), sorted(need3)):
            if k:
                keys[sha] = k; how['data3_marker'] += 1
            else:
                how['unresolved_d3_marker'] += 1
        for sha, k in ex.map(lambda s: mk(D4, s), sorted(need4)):
            if k:
                keys[sha] = k; how['data4_marker'] += 1
            else:
                # data-4 manifest row with a Disk-1/2 key?
                kinds = sorted({(x.get('key') or '').split(':')[0] for x in d4rows.get(sha, [])})
                how['unresolved_' + ('d4row_' + '+'.join(kinds) if kinds else 'no_d4row')] += 1
    json.dump(keys, open(os.path.join(INV, 'nc1_keys.json'), 'w'))
    put(os.path.join(INV, 'nc1_keys.json'), f'{RES}/inv/nc1_keys.json')
    log(f'resolve: {len(keys)} resolved; {dict(how)} ({time.time() - t0:.0f}s)')
    return dict(how)


def main():
    ph = sys.argv[1:] or ['steps', 'd3', 'd4', 'resolve']
    summ = {}
    sp = os.path.join(INV, 'inv_summary.json')
    if os.path.exists(sp):
        summ = json.load(open(sp))
    try:
        if 'steps' in ph:
            st = phase_steps()
            summ['steps'] = {'jobs': len(st), 'labels': dict(collections.Counter(l for d in st.values() for l in d))}
        if 'd3' in ph:
            summ['nc1_d3_rows'] = phase_scan('d3', f'{D3}/_state/manifests/')
        if 'd4' in ph:
            summ['nc1_d4_rows'] = phase_scan('d4', f'{D4}/_state/manifests/')
        if 'resolve' in ph:
            summ['resolve'] = phase_resolve()
    except Exception:
        traceback.print_exc()
        summ['error'] = traceback.format_exc()[-2000:]
    summ['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    json.dump(summ, open(sp, 'w'), indent=1)
    put(sp, f'{RES}/inv/inv_summary.json')
    log('inventory done', json.dumps(summ)[:2000])


if __name__ == '__main__':
    main()
