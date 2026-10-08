#!/usr/bin/env python3
"""Batch driver for sds2_ifc_recall.py over the data-3 SDS2 jobs that have a STEP in S3 and an IFC export of the same
job / project (work/candidates_ifc.json from find_candidates.py, IFC keys resolved from contents_ifc).
Downloads (AWS_PROFILE=bim, read only) into work/dl/, caches the IFC digest per sha and the STEP index per key,
writes out/ifc/<id>_<label>.json + .md, deletes the downloaded STEP after indexing.
usage: python run_ifc_batch.py [--ids id,id,...] [--max-step-mb 1300] [--max-ifc-mb 400] [--cross]
"""
import os, sys, json, subprocess, argparse, time, re, pickle, hashlib, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
B = 'bim-proprietary-data'
DL = os.path.join(HERE, 'work', 'dl'); os.makedirs(DL, exist_ok=True)
OUT = os.path.join(HERE, 'out', 'ifc'); os.makedirs(OUT, exist_ok=True)
CACHE = os.path.join(HERE, 'work', 'cache'); os.makedirs(CACHE, exist_ok=True)
ENV = dict(os.environ, AWS_PROFILE='bim')


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def s3get(key, dst):
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst
    tmp = dst + '.part'
    r = subprocess.run(['aws', 's3', 'cp', f's3://{B}/{key}', tmp, '--quiet'], env=ENV)
    if r.returncode != 0 or not os.path.exists(tmp):
        raise IOError(f'download failed: {key}')
    os.replace(tmp, dst)
    return dst


def s3size(key):
    r = subprocess.run(['aws', 's3api', 'head-object', '--bucket', B, '--key', key], env=ENV, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout).get('ContentLength')


def label_of(stepkey, lab):
    if '/v5.1/' in stepkey: return 'v5.1'
    if '/v5/' in stepkey: return 'v5'
    if 'sds2-step-r2-' in stepkey: return 'v4c-disk2r2'
    if 'zentitude-data-4' in stepkey: return 'v4c-data4'
    return 'v4-d3fleet' if lab == 'v4' else lab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids'); ap.add_argument('--max-step-mb', type=float, default=1300); ap.add_argument('--max-ifc-mb', type=float, default=400)
    ap.add_argument('--rels', default='same_name'); ap.add_argument('--extra', default='')
    ap.add_argument('--tol', type=float, default=25.0)
    a = ap.parse_args()
    import sds2_ifc_recall as R, ifc_products, stepidx
    C = json.load(open(os.path.join(HERE, 'work', 'candidates_ifc.json')))
    rels = set(a.rels.split(','))
    extra = {}
    for x in [e for e in a.extra.split(';') if e]:
        jid, isha = x.split(':')                # job id : ifc sha (use another job's IFC of the same project)
        extra.setdefault(jid, []).append(isha)
    ifc_by_sha = {h['sha256']: h for o in C for h in o['ifc']}
    todo = []
    for o in C:
        if a.ids and o['id'] not in a.ids.split(','):
            continue
        ifcs = [h for h in o['ifc'] if h['rel'] in rels][:1]
        ifcs += [ifc_by_sha[s] for s in extra.get(o['id'], []) if s in ifc_by_sha]
        if not ifcs:
            continue
        for lab, st in o['steps'].items():
            if lab.endswith('_not_accepted'):
                continue
            for h in ifcs:
                todo.append((o, lab, st, h))
    # jobs only referenced through --extra (no IFC of their own in the candidates)
    log(f'{len(todo)} (job, STEP, IFC) runs')
    todo.sort(key=lambda t: (t[3]['size'] + (t[2].get('size') or 3e8)))
    for o, lab, st, h in todo:
        key = st['key']; size = st.get('size') or s3size(key) or 0
        L = label_of(key, lab)
        tag = f"{o['id']}_{L}_{h['sha256'][:8]}"
        outj = os.path.join(OUT, tag + '.json')
        if os.path.exists(outj):
            log('skip (done)', tag); continue
        if size > a.max_step_mb * 1e6 or h['size'] > a.max_ifc_mb * 1e6:
            log('skip (size)', tag, size, h['size']); json.dump({'job_id': o['id'], 'label': L, 'status': 'skipped_size', 'step_bytes': size, 'ifc_bytes': h['size']}, open(outj, 'w')); continue
        try:
            icache = os.path.join(CACHE, f"ifc_{h['sha256'][:16]}.npz")
            if not os.path.exists(icache):
                ip = s3get(h['input_key'], os.path.join(DL, h['sha256'][:16] + '.ifc'))
                log('IFC digest', h['paths'][0][-80:], h['size'])
                d = ifc_products.digest(ip, threads=3, log=log)
                ifc_products.save(d, icache)
                os.remove(ip)
            scache = os.path.join(CACHE, 'step_' + hashlib.sha1(key.encode()).hexdigest()[:16] + '.pkl')
            if not os.path.exists(scache):
                sp = s3get(key, os.path.join(DL, os.path.basename(key)))
                log('STEP index', key[-90:], size)
                ix = stepidx.index_step(sp, log=log)
                pickle.dump(ix, open(scache, 'wb'))
                os.remove(sp)
            job = (o['paths'][0].split(' :: ')[-1].rstrip('/').split('/')[-1]) if o.get('paths') else o['id']
            res = R.run(key, icache, a.tol, L, job, log=log, index_cache=scache)
            res.update({'job_id': o['id'], 'ifc_rel': h['rel'], 'ifc_paths': h['paths'][:2], 'ifc_key': h['input_key'], 'step_key': key,
                        'job_paths': o.get('paths', [])[:3]})
            json.dump(res, open(outj, 'w'), indent=1, default=str)
            open(outj[:-5] + '.md', 'w').write(R.to_md(res))
            log('done', tag, res.get('overall'))
        except Exception as e:
            log('FAIL', tag, repr(e)[:300]); traceback.print_exc()
            json.dump({'job_id': o['id'], 'label': L, 'status': 'error', 'error': repr(e)[:500]}, open(outj, 'w'))


if __name__ == '__main__':
    main()
