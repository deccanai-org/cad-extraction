#!/usr/bin/env python3
"""Zenitude-data-3 independent verification (lead 20:10Z): every published STEP is checked by the format verifier of its pipeline
(ifc-step-verifier / db1-step-verifier / sds2_step_verifier, delivered as adapters next to this worker), in parallel with the grader.

Job list  _state/conv/verify/jobs.json (written by the coordinator)  {id: <pipe>-<model id>, vpipe, model_id, step_key, step_bytes,
          input_key (IFC / DB1 source) | files_key + name (SDS2 job folder), size, model_bytes}
Result    _state/conv/verify/results/<pipe>-<model id>.json  {pipeline, id, step_key, step_etag, verifier, verifier_version, verdict
          PASS|WARN|FAIL|CANNOT_VERIFY|ERROR, evidence, findings [{code, level, cause, count, detail}], missing | missing_csv_key, tier,
          runtime_s, peak_gb}; a verdict is current while step_key + ETag match the row's STEP (coordinator queues stale ones again)
Adapter   adapter_<pipe>.py --step STEP --source SRC --out OUT.json --id ID --workdir DIR   (python from adapter_<pipe>.json
          {"python": "env" | "sds2env" | "ifc84"}, default env; sds2 default sds2env); writes verdict / evidence / findings / missing / tier
"""
import os, sys, json, time, gzip, hashlib, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf

CODE = 'z3-verify-2026-10-02a'
W = os.environ.get('CONV_HOME', '/opt/conv')
PYS = {'env': os.path.join(W, 'env/bin/python'), 'sds2env': os.path.join(W, 'sds2env/bin/python'), 'ifc84': os.path.join(W, 'ifc84/bin/python'),
       'verifyenv': os.path.join(W, 'verifyenv/bin/python')}
ADAPTER = {'ifc': 'adapter_ifc.py', 'db1': 'adapter_db1.py', 'sds2': 'adapter_sds2.py'}
TIMEOUT = int(os.environ.get('VERIFY_TIMEOUT_S', str(4 * 3600)))
FILES = ('worker.py', 'convfleet.py', 'fetch.py', 'ifc_attrib.py')
VERDICTS = ('PASS', 'WARN', 'FAIL', 'CANNOT_VERIFY', 'ERROR')
SDS2_DIRS = {'main', 'mem', 'subm', 'pcm', 'jsetup'}


def sha_file(p):
    try:
        return cf.sha256_file(p)[:16]
    except Exception:
        return None


def need_bytes(job):
    """IFC / DB1 by STEP size (300 MB ~ 5 GB, 1-2 GB ~ 15-30 GB); SDS2 decodes the job: like stage 1, by the model size"""
    if job.get('vpipe') == 'attrib':
        return int(min(96 << 30, (1 << 30) + (job.get('size') or 0) * 10))
    if job.get('vpipe') == 'sds2':
        mb = (job.get('model_bytes') or job.get('size') or 0) >> 20
        for hi, gb in ((50, 4), (100, 8), (250, 16), (800, 24), (3000, 40)):
            if mb < hi:
                return gb << 30
        return 64 << 30
    sb = job.get('step_bytes') or 0
    if job.get('vpipe') == 'db1':                  # measured (adapter agent): 5 GB + 16 x STEP (+2 GB with a Tekla export)
        return int(min(96 << 30, (7 << 30) + sb * 16))
    return int(max(3 << 30, min(64 << 30, sb * 16 + (job.get('size') or 0) * 10)))   # IFC: max(3 GB, 16 x STEP + 10 x IFC)


def need_disk(job):
    return max(4 << 30, (job.get('step_bytes') or 0) * 3 + (job.get('size') or job.get('model_bytes') or 0) * 3)


def python_for(pipe):
    cfg = {}
    try:
        cfg = json.load(open(os.path.join(HERE, f'adapter_{pipe}.json')))
    except Exception:
        pass
    k = cfg.get('python') or ('sds2env' if pipe == 'sds2' else 'env')
    return PYS.get(k, PYS['env'])


def stage_sds2_job(fl, job, d):
    """the SDS2 job folder from its stored file list (as the SDS2 worker materializes it) -> folder path or (None, error)"""
    body = cf.s3.get_object(Bucket=cf.B, Key=job['files_key'])['Body'].read()
    try:
        body = gzip.decompress(body)
    except OSError:
        pass
    mf = json.loads(body)
    name = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in (job.get('name') or 'job')) + '_' + job['model_id'][:6]
    root = os.path.join(d, 'job', name); items = []
    for f in mf:
        parts = [p for p in f['p'].replace('\\', '/').split('/') if p]
        if parts and parts[0].lower() in SDS2_DIRS:
            parts[0] = parts[0].lower()
        items.append([f.get('key') or '', os.path.join(root, *parts), f['size']])
    lst = os.path.join(d, 'fetch.json'); json.dump(items, open(lst, 'w'))
    rc, out, err = fl.sh([PYS['sds2env'] if os.path.exists(PYS['sds2env']) else PYS['env'], os.path.join(HERE, 'fetch.py'), lst, '48'], timeout=7200)
    try:
        fr = json.loads(out.strip().splitlines()[-1])
    except Exception:
        return None, f'fetch: {(err or out)[-200:]}'
    if fr.get('n_errors'):
        return None, f'fetch: {fr.get("n_errors")} errors'
    return root, None


_TREE = {}


def ensure_tree(pipe):
    """the adapter's support files on control (verify/<pipe>/..., e.g. the teammate's verifier) -> HERE/<pipe>/ (kit sync skips sub-folders);
    refreshed when their listing changes, checked at most every 5 min"""
    t = _TREE.get(pipe)
    if t and time.time() - t[0] < 300:
        return
    root = 'cad-disk-extract/_control/z3conv/verify/'
    subs = {'sds2': ['sds2/'], 'ifc': ['ifc/', 'ifcstepverify/'], 'db1': ['db1/', 'db1stepverify/']}.get(pipe, [pipe + '/'])
    objs = [o for sub in subs for pg in cf.s3.get_paginator('list_objects_v2').paginate(Bucket=cf.CB, Prefix=root + sub) for o in pg.get('Contents', [])]
    sig = sorted((o['Key'], o['ETag']) for o in objs)
    if t and t[1] == sig:
        _TREE[pipe] = (time.time(), sig); return
    for o in objs:
        rel = o['Key'][len(root):]
        if not rel or rel.endswith('/'):
            continue
        dst = os.path.join(HERE, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
        cf.s3.download_file(cf.CB, o['Key'], dst + '.part'); os.replace(dst + '.part', dst)
    _TREE[pipe] = (time.time(), sig)


def attrib(fl, job, d):
    """[z3v rules 1-3] cause attribution of an IFC model's surface / missing parts (ifc_attrib.py on the source + both part lists)"""
    rec = {'pipeline': 'attrib', 'id': job.get('model_id')}
    src = os.path.join(d, 'source' + os.path.splitext(job['input_key'])[1][:8]); cp = os.path.join(d, 'src_parts.jsonl.gz'); sp = os.path.join(d, 'step_parts.jsonl.gz')
    try:
        cf.s3.download_file(cf.B, job['input_key'], src); cf.s3.download_file(cf.B, job['src_parts_key'], cp); cf.s3.download_file(cf.B, job['step_parts_key'], sp)
    except Exception as e:
        return dict(rec, status='fail', reason='download_error', error=f'{type(e).__name__}: {str(e)[:160]}')
    out = os.path.join(d, 'attrib.json')
    rc = fl.run(job['id'], [PYS['env'], os.path.join(HERE, 'ifc_attrib.py'), src, cp, sp, out, '--unpack-dir', d, '--closed-surface-models', 'pipeline'], os.path.join(d, 'attrib.log'), 3 * 3600)
    if rc != 0 or not os.path.exists(out):
        return dict(rec, status='fail', reason='attrib_failed', rc=rc)
    fl.upload(out, job['out_key'])
    return dict(rec, status='ok', out_key=job['out_key'])


def process(fl, job, d):
    if job.get('vpipe') == 'attrib':
        return attrib(fl, job, d)
    pipe = job.get('vpipe'); mid = job.get('model_id'); sk = job.get('step_key')
    rec = {'pipeline': pipe, 'id': mid, 'step_key': sk}
    prev = fl.getj(f'{fl.ST}/results/{job["id"]}.json') or {}
    if prev.get('verdict') in ('ERROR', 'CANNOT_VERIFY') and prev.get('step_key') == sk:
        rec['retried'] = True                        # the one retry of an ERROR / CANNOT_VERIFY verdict
    ad = os.path.join(HERE, ADAPTER.get(pipe, ''))
    if not pipe or not os.path.exists(ad):
        return dict(rec, status='fail', reason='adapter_unavailable', transient=True)
    try:
        h = cf.s3.head_object(Bucket=cf.B, Key=sk)
    except Exception as e:
        return dict(rec, status='fail', reason='step_missing', detail=f'{type(e).__name__}')
    rec['step_etag'] = h['ETag'].strip('"'); rec['step_bytes'] = h['ContentLength']
    t0 = time.time()
    try:
        ensure_tree(pipe)
    except Exception as e:
        return dict(rec, status='fail', reason='adapter_tree_unavailable', transient=True, error=f'{type(e).__name__}: {str(e)[:160]}')
    sd = os.path.join(d, 'step'); os.makedirs(sd, exist_ok=True)
    stp = os.path.join(sd, sk.rsplit('/', 1)[-1])
    cf.s3.download_file(cf.B, sk, stp)
    base = sk.rsplit('.', 1)[0]
    for o in cf.s3.list_objects_v2(Bucket=cf.B, Prefix=base + '_').get('Contents', []):
        if o['Key'].endswith(('.csv', '.json')) and o['Size'] < (2 << 30):
            cf.s3.download_file(cf.B, o['Key'], os.path.join(sd, o['Key'].rsplit('/', 1)[-1]))   # converter siblings (pieces / skipped / manifest)
    if pipe == 'sds2':
        src, err = stage_sds2_job(fl, job, d)
        if not src:
            return dict(rec, status='fail', reason='download_error', transient=True, error=err)
    else:
        if not job.get('input_key'):
            return dict(rec, status='fail', reason='source_missing')
        src = os.path.join(d, 'source' + os.path.splitext(job['input_key'])[1][:8])
        cf.s3.download_file(cf.B, job['input_key'], src)
    out = os.path.join(d, 'verdict.json'); logf = os.path.join(d, 'verify.log'); wd = os.path.join(d, 'w'); os.makedirs(wd, exist_ok=True)
    py = python_for(pipe)
    extra = []
    sg = os.path.join(HERE, pipe, 'stage_gt.py')
    if os.path.exists(sg):                                 # ground truth (IFC / KISS / NC1) stored next to the job in the source
        gd = os.path.join(d, 'gt'); os.makedirs(gd, exist_ok=True)
        fl.sh([py, sg, '--id', mid, '--dest', gd], timeout=900)
        if any(files for _, _, files in os.walk(gd)):
            extra = ['--gt-dir', gd]
    if pipe == 'db1':
        recp = os.path.join(d, 'record.json')
        try:
            cf.s3.download_file(cf.B, f'{cf.ROOT}/_state/conv/db1/results/{mid}.json', recp); extra += ['--record', recp]
        except Exception:
            pass
        tm = os.path.join(HERE, 'db1', 'truth_map.json')
        if os.path.exists(tm):
            extra += ['--truth-map', tm]
    if pipe in ('ifc', 'db1'):
        extra += ['--threads', '2']
    rc = fl.run(job['id'], [py, ad, '--step', stp, '--source', src, '--out', out, '--id', mid, '--workdir', wd] + extra, logf, TIMEOUT)
    for ext in ('.missing.csv', '.full.json', '.step.png', '.vs_tekla.png'):     # the adapter's side outputs next to R.json
        sp = out[:-5] + ext
        if os.path.exists(sp):
            try:
                fl.upload(sp, f'{cf.ROOT}/_state/conv/verify/detail/{job["id"]}{ext}'); rec.setdefault('detail_keys', []).append(f'{cf.ROOT}/_state/conv/verify/detail/{job["id"]}{ext}')
            except Exception:
                pass
    rec.update(verifier=os.path.basename(ad), verifier_version=sha_file(ad), runtime_s=round(time.time() - t0, 1),
               peak_gb=round(((fl.running.get(job['id']) or {}).get('peak_rss') or 0) / 2 ** 30, 2), rc=rc)
    v = None
    try:
        v = json.load(open(out))
    except Exception:
        v = None
    if not isinstance(v, dict) or v.get('verdict') not in VERDICTS:
        tail = ''
        try:
            tail = open(logf, errors='replace').read()[-800:]
        except Exception:
            pass
        rec.update(verdict='ERROR', evidence=None, findings=[{'code': 'verifier_no_verdict', 'level': 'error', 'cause': 'unclassified',
                                                              'count': 1, 'detail': f'rc {rc}: {tail[-300:]}'}])
        return dict(rec, status='ok', log_tail=tail)
    for k in ('verdict', 'evidence', 'findings', 'missing', 'missing_csv_key', 'tier', 'tier_confidence', 'class1_ok', 'class1_reasons',
              'index_missing', 'index_needed_to_fix', 'verifier', 'verifier_version', 'summary'):
        if k in v and v[k] is not None:
            rec[k] = v[k]
    mc = v.get('missing_csv')
    if isinstance(mc, str) and os.path.exists(mc):
        mk = f'{cf.ROOT}/_state/conv/verify/detail/{job["id"]}.missing.csv'
        fl.upload(mc, mk); rec['missing_csv_key'] = mk
    if isinstance(rec.get('missing'), list) and len(rec['missing']) > 500:
        mk = f'{cf.ROOT}/_state/conv/verify/detail/{job["id"]}.missing.json.gz'; mp = os.path.join(d, 'missing.json.gz')
        with gzip.open(mp, 'wt') as g:
            json.dump(rec['missing'], g)
        fl.upload(mp, mk); rec['missing_key'] = mk
        rec['missing_count'] = len(rec['missing']); rec['missing'] = rec['missing'][:500]
    else:
        rec['missing_count'] = len(rec.get('missing') or [])
    try:
        fl.put(f'{cf.ROOT}/_state/conv/verify/{pipe}/{mid}.json', dict(rec, status='ok', code=CODE, at=cf.now()))   # per-model copy (lead's path)
    except Exception:
        pass
    return dict(rec, status='ok')


def redo(r):
    """an ERROR / CANNOT_VERIFY verdict gets one retry (lead 20:10Z); the coordinator re-queues stale verdicts (STEP changed)"""
    return r.get('verdict') in ('ERROR', 'CANNOT_VERIFY') and not r.get('retried')


if __name__ == '__main__':
    fl = cf.Fleet('verify', CODE, process, need_bytes, FILES, need_disk=need_disk, redo=redo)
    sys.exit(fl.main())
