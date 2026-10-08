"""Status + S3 sync daemon.

status.py once          -> write status JSON once
status.py loop [--sync-every 300] [--every 60]
Writes s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/s3d3d_status.json and syncs
/data/s3d/out/ -> s3://annotationprod/cad-disk-extract/zenitude-data-2/model/ (the only S3 targets used).
"""
import os, sys, json, time, glob, subprocess, collections
from common import *

STAGE_F = os.path.join(WORK, 'stage.txt')


def count(pattern):
    return len(glob.glob(os.path.join(OUT, pattern), recursive=True))


def dir_bytes(sub):
    tot = 0
    for dp, dn, fn in os.walk(os.path.join(OUT, sub)):
        for f in fn:
            try:
                tot += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return tot


def failures():
    out = []
    for d in ('piping',):
        for f in glob.glob(os.path.join(WORK, 'done', d, '*.json')):
            try:
                j = json.load(open(f))
            except Exception:
                continue
            for r in j.get('results', []):
                if 'error' in r:
                    out.append({'stage': 'json/pcf', 'item': r.get('pl'), 'reason': r['error'][:200]})
    for stage in ('ifc', 'convert', 'struct', 'equip'):
        fp = os.path.join(WORK, 'fail', stage + '.jsonl')
        if os.path.exists(fp):
            for line in open(fp):
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def build():
    st = collections.OrderedDict()
    st['stage'] = open(STAGE_F).read().strip() if os.path.exists(STAGE_F) else 'starting'
    st['updated'] = utcnow()
    st['source'] = 'Hexagon Smart 3D v13 model MLNG@1 (MLNG@1_MDB/CDB), licence-free extraction'
    st['s3_root'] = 's3://%s/%s/' % (S3_BUCKET, S3_PREFIX)
    c = collections.OrderedDict()
    try:
        c['pipelines_total'] = len(load_pkl('pipelines'))
    except Exception:
        c['pipelines_total'] = 45003
    c['json_written'] = count('json/pipelines/*.json.gz')
    c['pcf_written'] = count('pcf/**/*.pcf')
    c['structure_area_files'] = count('json/structure/*.jsonl.gz')
    c['equipment_area_files'] = count('json/equipment/*.jsonl.gz')
    c['ifc_files'] = count('ifc/**/*.ifc')
    c['step_files'] = count('step/**/*.step') + count('step/**/*.stp')
    c['step_validated'] = count('step/**/*.validate.json')
    c['gltf_files'] = count('gltf/**/*.glb')
    c['obj_files'] = count('obj/**/*.obj')
    c['png'] = count('png/**/*.png')
    st['counts'] = c
    try:
        import agg_piping
        s = agg_piping.summary()
        st['piping_validation'] = {'pipelines_ok': s['pipelines_ok'], 'pipelines_error': s['pipelines_error'],
                                   'checks': s['checks'], 'pcf_points': {k: v for k, v in s['pcf'].items() if k.startswith('points') or k in ('setback_snapped',)},
                                   'component_types': s['types']}
    except Exception as e:
        st['piping_validation'] = {'error': str(e)[:200]}
    for name, key in (('pcf_validation', 'pcf_validation'), ('acis_summary', 'acis')):
        pth = os.path.join(WORK, name + '.json')
        if os.path.exists(pth):
            try:
                st[key] = json.load(open(pth))
            except Exception:
                pass
    pp = os.path.join(OUT, 'pairs', 'summary.json')
    if os.path.exists(pp):
        try:
            st['pairs'] = json.load(open(pp))
        except Exception:
            pass
    for name in ('ifc_summary', 'convert_summary', 'struct_summary', 'equip_summary'):
        p = os.path.join(WORK, name + '.json')
        if os.path.exists(p):
            try:
                st[name] = json.load(open(p))
            except Exception:
                pass
    fo = os.path.join(WORK, 'fanout.json')
    if os.path.exists(fo):
        try:
            st['fanout'] = json.load(open(fo)); st['fanout_ready'] = bool(st['fanout'].get('fanout_ready'))
            st['fanout_progress'] = fanout_progress()
            fp = st['fanout_progress']
            c['step_files_s3'] = fp.get('step_ok', 0); c['gltf_files_s3'] = fp.get('glb_ok', 0); c['obj_files_s3'] = fp.get('obj_ok', 0)
            c['png_s3'] = fp.get('png', 0); c['step_validated_s3'] = fp.get('occ_read_ok', 0)
        except Exception as e:
            st['fanout_error'] = str(e)[:200]
    f = failures()
    st['failures_total'] = len(f)
    st['failures'] = f[:200]
    return st


_fp_cache = {'t': 0, 'v': {}, 'seen': {}}


def fanout_progress():
    """aggregate fan-out results from s3 (_state/s3d3d/results), cached incrementally"""
    import boto3
    s3 = boto3.client('s3')
    pre = 'cad-disk-extract/zenitude-data-2/_state/s3d3d/'
    seen = _fp_cache['seen']
    listed = set()
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET, Prefix=pre + 'results/'):
        for o in page.get('Contents', []):
            k = o['Key']; listed.add(k)
            if k in seen and seen[k][0] == o['ETag']:
                continue
            try:
                r = json.loads(s3.get_object(Bucket=S3_BUCKET, Key=k)['Body'].read())
            except Exception:
                continue
            seen[k] = (o['ETag'], r)
    for k in list(seen):
        if k not in listed:
            del seen[k]
    agg = collections.Counter(); fails = []
    for k, (_, r) in seen.items():
        agg['results'] += 1
        if 'error' in r:
            agg['errors'] += 1; fails.append({'stage': 'fanout', 'item': r.get('id'), 'reason': r['error'][:200]}); continue
        for x in ('step', 'glb', 'obj'):
            if x in r:
                agg[x + ('_ok' if r[x].get('ok') else '_fail')] += 1
                agg[x + '_mb'] += (r[x].get('bytes') or 0) / 1e6
        v = r.get('validate') or {}
        if v.get('read_status') == 'ok':
            agg['occ_read_ok'] += 1
            agg['occ_roots_eq_parts'] += 1 if v.get('roots_match_parts') else 0
        elif v.get('skipped'):
            agg['occ_skipped_size'] += 1
        elif v:
            agg['occ_read_fail'] += 1
        agg['png'] += len((r.get('png') or {}).get('keys', []))
    claims = sum(len(p.get('Contents', [])) for p in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET, Prefix=pre + 'claims/'))
    workers = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET, Prefix=pre + 'workers/'):
        for o in page.get('Contents', []):
            try:
                workers.append(json.loads(s3.get_object(Bucket=S3_BUCKET, Key=o['Key'])['Body'].read()))
            except Exception:
                pass
    out = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in agg.items()}
    out['claims'] = claims; out['workers'] = workers; out['failures_sample'] = fails[:50]
    return out


def put_status(st):
    import boto3
    boto3.client('s3').put_object(Bucket=S3_BUCKET, Key=S3_STATE, Body=json.dumps(st, indent=1, default=str).encode(),
                                  ContentType='application/json', CacheControl='no-cache')


_sync = {'proc': None, 't0': 0, 'last': None}


def sync_tick(sync_every):
    """non-blocking aws s3 sync of OUT -> model/ (at most one running)"""
    p = _sync['proc']
    if p is not None:
        if p.poll() is None:
            return {'running': True, 'since_s': round(time.time() - _sync['t0'])}
        err = p.stderr.read().decode(errors='replace')[-300:] if p.stderr else ''
        _sync['last'] = {'rc': p.returncode, 'sec': round(time.time() - _sync['t0'], 1), 'finished': utcnow(), 'err': err}
        _sync['proc'] = None
    if time.time() - _sync['t0'] > sync_every:
        _sync['t0'] = time.time()
        _sync['proc'] = subprocess.Popen(['aws', 's3', 'sync', '--only-show-errors', OUT + '/', 's3://%s/%s/' % (S3_BUCKET, S3_PREFIX),
                                          '--exclude', '*.tmp*'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return {'started': utcnow(), 'last': _sync['last']}
    return {'last': _sync['last']}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'once'
    every = 60; sync_every = 300
    if '--every' in sys.argv:
        every = int(sys.argv[sys.argv.index('--every') + 1])
    if '--sync-every' in sys.argv:
        sync_every = int(sys.argv[sys.argv.index('--sync-every') + 1])
    while True:
        try:
            st = build()
            if mode == 'loop':
                st['sync'] = sync_tick(sync_every)
            put_status(st)
            log('status: %s %s' % (st['stage'], json.dumps(st['counts'])))
        except Exception as e:
            log('status error %s' % e)
        if mode != 'loop':
            break
        if os.path.exists(os.path.join(WORK, 'status.stop')):
            break
        time.sleep(every)


if __name__ == '__main__':
    main()
