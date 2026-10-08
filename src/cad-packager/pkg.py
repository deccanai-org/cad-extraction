#!/usr/bin/env python3
"""General CAD packager CLI + coordinator hook + fleet job.  See SPEC.md.

  pkg.py plan   --adapter zen3 [--projects ID,..|--job-ids ID,..|--all] [--out DIR|--s3-out]   read-only dry run
  pkg.py job    --job JOB.json|s3key        one 'package' job: lock -> plan -> apply -> verify -> ledger part   (fleet only)
  pkg.py delta  --adapter zen3 [--write]    coordinator round: shipped set - ledger -> jobs; removals queue; status
  pkg.py verify --adapter zen3 [--projects ..|--all] [--full-hash]
  pkg.py compact                             ledger_parts -> ledger.jsonl + ledger_index.json
Apply/job/delta --write need PKG_ALLOW_WRITE=1 (set only on the fleet; the operator Mac never writes the dataset).
"""
from __future__ import annotations
import argparse, collections, gzip, hashlib, importlib, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import pkgcore as pc

JOBS_KEY = os.environ.get('PKG_JOBS_KEY', 'cad-disk-extract/zenitude-data-3/_state/conv/package/jobs.json')
LOCK_STALE_S = int(os.environ.get('PKG_LOCK_STALE_S', '7200'))


def log(*a):
    print(pc.now(), *a, flush=True)


def load_adapter(name, **kw):
    try:
        mod = importlib.import_module(f'adapters.{name}')
    except ImportError:
        mod = importlib.import_module(f'adapter_{name}')          # flat fleet kit (kit sync copies top-level files only)
    return mod.Adapter(**kw)


def must_write():
    if os.environ.get('PKG_ALLOW_WRITE') != '1':
        sys.exit('refusing to write: PKG_ALLOW_WRITE=1 is set only on the fleet (plan is the read-only dry run)')


# ---------------------------------------------------------------- shipped set -> projects
def shipped_by_project(adapter, rows, policy=None):
    shipped = {}; why = collections.Counter()
    for r in rows:
        ok, reason = pc.ship_decision(r, policy)
        why[reason.split(':')[0] if not ok else 'shipped'] += 1
        if ok: shipped[r['model_key']] = r
    targets = collections.defaultdict(set); refs = {}; nots = collections.defaultdict(list); unknown = set()
    for mk, r in shipped.items():
        for a, m in r['source_paths']:
            ref = adapter.project_ref(a)
            if not ref: unknown.add(a); continue
            refs[ref['project_id']] = ref; targets[ref['project_id']].add(mk)
    for r in rows:
        if r['model_key'] in shipped: continue
        for pid in {adapter.project_of(a) for a, m in r['source_paths']} & set(targets):
            nots[pid].append(r)
    return shipped, targets, refs, nots, why, unknown


def step_heads(rows, threads=32):
    with ThreadPoolExecutor(threads) as tp:
        hs = list(tp.map(lambda r: (r['step_key'], pc.head(r.get('step_bucket') or pc.BUCKET, r['step_key'])), rows))
    return dict(hs)


# ---------------------------------------------------------------- plan (dry run)
def cmd_plan(a):
    ad = load_adapter(a.adapter, cache_dir=a.cache_dir)
    idx_bytes = open(a.index, 'rb').read() if a.index else None
    rows = ad.conv_rows(idx_bytes)
    shipped, targets, refs, nots, why, unknown = shipped_by_project(ad, rows, a.policy and json.load(open(a.policy)))
    log(f'index rows {len(rows)}; ship decisions {dict(why)}; shipped {len(shipped)}; projects {len(targets)}; '
        f'unknown archives {len(unknown)}')
    sel = sorted(targets)
    if a.job_ids:
        want = set(a.job_ids.split(',')); sel = [p for p in sel if refs[p]['job_id'] in want]
    elif a.projects:
        want = set(a.projects.split(',')); sel = [p for p in sel if p in want]
    elif not a.all:
        sys.exit('choose --job-ids, --projects or --all')
    if a.shard:
        i, n = map(int, a.shard.split('/')); sel = [p for k, p in enumerate(sel) if k % n == i]
    heads = step_heads([shipped[mk] for p in sel for mk in targets[p]])
    os.makedirs(a.out, exist_ok=True)
    summ = {'planned_at': pc.now(), 'packager': pc.VERSION, 'adapter': a.adapter, 'index_rows': len(rows),
            'ship_decisions': dict(why), 'shipped_models': len(shipped), 'projects_total': len(targets),
            'projects_planned': len(sel), 'unknown_archives': sorted(unknown)[:20], 'projects': []}
    ids = collections.Counter(refs[p]['project_id'] for p in sel)
    assert all(v == 1 for v in ids.values()), 'project id collision'
    for pid in sel:
        t0 = time.time()
        plan = pc.plan_project(ad, refs[pid], [shipped[mk] for mk in targets[pid]], nots.get(pid, []), step_heads=heads,
                               index_ref={'key': a.index or 'live', 'rows': len(rows)})
        fn = os.path.join(a.out, refs[pid]['job_id'] + '.plan.json' + ('.gz' if a.gz else ''))
        with (gzip.open(fn, 'wt') if a.gz else open(fn, 'w')) as fo:
            json.dump(plan, fo, indent=None if a.gz else 1, ensure_ascii=False)
        s = plan['stats']
        summ['projects'].append({'project_id': pid, 'job_id': refs[pid]['job_id'], 'status': plan['status'], 'files': s['files'],
                                 'bytes': s['bytes'], 'steps': s['steps'], 'step_bytes': s['step_bytes'], 'zips': s['zips'],
                                 'zip_member_bytes': s['zip_member_bytes'], 'unresolved': s['unresolved'],
                                 'unresolved_bytes': s['unresolved_bytes'], 'resolved_by': s['resolved_by'],
                                 'channels': s['channels'], 'steps_not_shipped': len(plan['steps_not_shipped']),
                                 'native_steps_not_graded': len(plan['native_steps_not_graded']),
                                 'excluded_non_asset_files': plan['excluded_non_asset_files'],
                                 'duplicates_collapsed': plan['duplicates_collapsed'], 'plan_s': round(time.time() - t0, 1)})
        log(f"{pid[:90]}: {plan['status']} files={s['files']} steps={s['steps']} zips={s['zips']} unresolved={s['unresolved']} "
            f"by={s['resolved_by']}")
    tot = collections.Counter()
    for p in summ['projects']:
        for k in ('files', 'bytes', 'steps', 'step_bytes', 'zips', 'zip_member_bytes', 'unresolved', 'unresolved_bytes',
                  'steps_not_shipped', 'native_steps_not_graded'):
            tot[k] += p[k]
        tot['projects_ok'] += p['status'] == 'ok'
    summ['totals'] = dict(tot)
    json.dump(summ, open(os.path.join(a.out, f"summary{('.' + a.shard.replace('/', '_of_')) if a.shard else ''}.json"), 'w'), indent=1)
    log('totals', dict(tot))


# ---------------------------------------------------------------- locks / job (fleet)
def lock(pid, owner):
    from botocore.exceptions import ClientError
    k = f'{pc.PSTATE}/locks/{pid}.json'
    body = {'owner': owner, 'host': os.uname()[1], 'at': pc.now()}
    try:
        pc.put_json(pc.BUCKET, k, body, if_none_match=True); return True
    except ClientError as e:
        if e.response.get('Error', {}).get('Code') not in ('PreconditionFailed', '412', 'ConditionalRequestConflict', '409'):
            raise
    h = pc.head(pc.BUCKET, k)
    if h and time.time() - h['LastModified'].timestamp() > LOCK_STALE_S:
        try:
            pc.put_json(pc.BUCKET, k, dict(body, took_over=True), if_match=h['ETag']); return True
        except ClientError:
            return False
    return False


def unlock(pid):
    try:
        pc.s3c().delete_object(Bucket=pc.BUCKET, Key=f'{pc.PSTATE}/locks/{pid}.json')   # own lock object only
    except Exception:
        pass


def package_job(job, adapter=None, workdir='/tmp/pkgwork'):
    """one 'package' job (vpipe package).  Returns a result dict {status: ok|fail|retry, ...}."""
    must_write()
    ad = adapter or load_adapter(job.get('adapter', 'zen3'))
    pid = job['project_id']
    if not lock(pid, job['id']):
        return {'status': 'retry', 'reason': 'project_locked', 'project_id': pid}
    stop = threading.Event()

    def keep():
        while not stop.wait(300):
            try: pc.put_json(pc.BUCKET, f'{pc.PSTATE}/locks/{pid}.json', {'owner': job['id'], 'at': pc.now(), 'refresh': True})
            except Exception: pass
    threading.Thread(target=keep, daemon=True).start()
    try:
        idx = pc.get_bytes(pc.BUCKET, job['index_key'])
        rows = ad.conv_rows(idx)
        shipped, targets, refs, nots, why, unknown = shipped_by_project(ad, rows, job.get('policy'))
        if pid not in refs:
            return {'status': 'ok', 'project_id': pid, 'note': 'no shipped STEP for this project in the snapshot (nothing to do)'}
        base = f'{pc.DATASET}/{pc.ROUTE}/{pid}'
        existing = pc.read_manifest(pc.BUCKET, base)
        existing_pj = pc.get_json(pc.BUCKET, f'{base}/project.json') if existing else None
        sh = [shipped[mk] for mk in targets[pid]]
        plan = pc.plan_project(ad, refs[pid], sh, nots.get(pid, []), existing=existing or None, existing_pj=existing_pj,
                               index_ref={'key': job['index_key'], 'job': job['id']}, policy=job.get('policy'))
        pc.put_json(pc.BUCKET, f"{pc.PSTATE}/plans/{pid}/{job['id']}.json.gz", plan, gz=True)
        if plan['status'] != 'ok':
            return {'status': 'ok', 'project_id': pid, 'note': plan['status']}
        if existing and not plan['steps'] and not plan['sds2_zips']:
            # nothing to copy: refresh project.json (steps_not_shipped may have changed)
            pj = pc.project_json(plan, existing)
            pc.s3c().put_object(Bucket=pc.BUCKET, Key=f'{base}/project.json', Body=json.dumps(pj, indent=1, ensure_ascii=False).encode(),
                                ContentType='application/json')
            rec = {'status': 'ok', 'copied': 0, 'failed': []}
        else:
            rec = pc.apply_plan(plan, workdir=workdir)
        shipped_keys = {r['id']: r['step_key'] for r in sh}
        pending_removal = {r.get('model_id') for r in existing if r.get('modality') == 'step' and r.get('model_id') not in shipped_keys}
        for m in pending_removal:                       # queued for the owner, still present: not a verify failure
            shipped_keys[m] = next((r['step_key'] for r in existing if r.get('model_id') == m), None)
        ver = pc.verify_project(pc.BUCKET, pid, shipped_keys)
        out = {'project_id': pid, 'job_id': job['id'], 'at': pc.now(), 'apply': {k: rec.get(k) for k in ('status', 'copied',
               'skipped_existing', 'failed', 'files')}, 'verify': ver, 'pending_removal': sorted(filter(None, pending_removal)),
               'index_key': job['index_key'], 'packager': pc.VERSION}
        if ver['ok'] and rec.get('status') in ('ok', 'partial'):
            man = pc.read_manifest(pc.BUCKET, base)
            pc.put_json(pc.BUCKET, f'{pc.PSTATE}/ledger_parts/{pid}.json', pc.ledger_part(plan, man, ver))
            pc.put_json(pc.BUCKET, f'{pc.PSTATE}/done/{pid}.json', dict(out, files=len(man), bytes=sum(r['bytes'] for r in man)))
            vf = pc.get_json(pc.BUCKET, f'{pc.PSTATE}/verify_fail/{pid}.json')
            if vf and not vf.get('resolved'):
                pc.put_json(pc.BUCKET, f'{pc.PSTATE}/verify_fail/{pid}.json', dict(vf, resolved=True, resolved_at=pc.now(), resolved_by=job['id']))
            return dict(out, status='ok')
        prevf = pc.get_json(pc.BUCKET, f"{pc.PSTATE}/verify_fail/{pid}.json") or {}
        pc.put_json(pc.BUCKET, f"{pc.PSTATE}/verify_fail/{pid}.json", dict(out, attempts=int(prevf.get('attempts', 0)) + 1))
        return dict(out, status='fail', reason='verify_failed' if not ver['ok'] else rec.get('status'))
    finally:
        stop.set(); unlock(pid)


def cmd_job(a):
    job = json.load(open(a.job)) if os.path.exists(a.job) else pc.get_json(pc.BUCKET, a.job)
    r = package_job(job, workdir=a.workdir)
    print(json.dumps({k: v for k, v in r.items() if k != 'verify'}, indent=1)[:4000])
    sys.exit(0 if r['status'] == 'ok' else 2)


# ---------------------------------------------------------------- coordinator hook
def pkg_delta(adapter_name='zen3', index_bytes=None, policy=None, write=False, jobs_key=JOBS_KEY):
    """Called by the coordinator each round.  Returns (jobs, status).  write=True (fleet) also stores:
    the index snapshot, the jobs list (jobs_key), removals_pending.jsonl (new entries appended), status.json, compacted ledger."""
    ad = load_adapter(adapter_name)
    idx = index_bytes if index_bytes is not None else pc.get_bytes(pc.BUCKET, ad_index_key(ad))
    snap = f"{pc.PSTATE}/index_snapshots/{hashlib.sha256(idx).hexdigest()[:16]}.jsonl.gz"
    rows = ad.conv_rows(idx)
    shipped, targets, refs, nots, why, unknown = shipped_by_project(ad, rows, policy)
    heads = step_heads(list(shipped.values()))
    _, lidx = pc.compact_ledger(pc.BUCKET, write=write)
    pairs = {(mk, pid) for mk, e in lidx.items() for pid in e['projects']}
    jobs = []
    prev = (pc.get_json(pc.BUCKET, jobs_key) or {}).get('jobs') or []
    rp = os.environ.get('PKG_RESULTS_PREFIX', jobs_key.rsplit('/', 1)[0] + '/results/')
    done_ids = {k.rsplit('/', 1)[-1][:-5] for k, _, _ in pc.list_keys(pc.BUCKET, rp)} if prev else set()
    open_prev = {j['project_id']: j for j in prev if j['id'] not in done_ids}
    vfd = {k.rsplit('/', 1)[-1][:-5]: pc.get_json(pc.BUCKET, k) or {} for k, _, _ in pc.list_keys(pc.BUCKET, f'{pc.PSTATE}/verify_fail/')}
    fails = {p for p, d in vfd.items() if not d.get('resolved')}
    stuck = 0
    for pid in sorted(targets):
        if pid in open_prev:                          # an unfinished job for this project keeps its id (no second job)
            jobs.append(open_prev[pid]); continue
        add = sorted(mk for mk in targets[pid] if (mk, pid) not in pairs)
        ref_ = []
        for mk in sorted(targets[pid]):
            if (mk, pid) in pairs:
                e = lidx[mk]; hd = heads.get(shipped[mk]['step_key'])
                if e['step_key'] != shipped[mk]['step_key'] or (hd and e.get('step_etag') != hd['ETag'].strip('"')):
                    ref_.append(mk)
        if add or ref_:
            if pid in fails and int(vfd[pid].get('attempts', 1)) >= 3:
                stuck += 1; continue                  # 3 failed verifies: left for an operator (status 'verify_failures')
            sig = hashlib.sha256(json.dumps([add, ref_, snap, pc.now()]).encode()).hexdigest()[:10]
            jobs.append({'id': f"pkg-{hashlib.sha1(pid.encode()).hexdigest()[:16]}-{sig}", 'vpipe': 'package',
                         'adapter': adapter_name, 'project_id': pid, 'archive': refs[pid]['source_key'],
                         'kind': 'update' if any(p == pid for _, p in pairs) else 'create', 'add': add, 'refresh': ref_,
                         'index_key': snap, 'policy': policy, 'size': refs[pid].get('size') or 0})
    removals = []
    for mk, pid in sorted(pairs):
        if mk not in shipped or pid not in targets or mk not in targets[pid]:
            r = next((x for x in rows if x['model_key'] == mk), None)
            removals.append({'model_key': mk, 'project_id': pid, 'relpath': None, 'reason': ('left shipped set: ' +
                             pc.ship_decision(r, policy)[1]) if r else 'model no longer in the index', 'queued_at': pc.now()})
    vf = len(fails)
    status = {'updated': pc.now(), 'packager': pc.VERSION, 'shipped_models': len(shipped), 'ship_decisions': dict(why),
              'projects_with_shipped_step': len(targets), 'projects_packaged': len({p for _, p in pairs}),
              'steps_placed_models': len(lidx), 'placements': len(pairs), 'pending_jobs': len(jobs),
              'pending_create': sum(1 for j in jobs if j['kind'] == 'create'),
              'pending_steps': sum(len(j['add']) + len(j['refresh']) for j in jobs),
              'removals_pending': len(removals), 'verify_failures': vf, 'stuck_projects': stuck, 'unknown_archives': len(unknown),
              'index_snapshot': snap}
    if write:
        must_write()
        if not pc.head(pc.BUCKET, snap):
            pc.s3c().put_object(Bucket=pc.BUCKET, Key=snap, Body=idx, ContentType='application/gzip')
        pc.put_json(pc.BUCKET, jobs_key, {'updated': pc.now(), 'jobs': sorted(jobs, key=lambda j: -j['size'])})
        prev = pc.get_bytes(pc.BUCKET, f'{pc.PSTATE}/removals_pending.jsonl') or b''
        have = {(json.loads(l)['model_key'], json.loads(l)['project_id']) for l in prev.decode().splitlines() if l.strip()}
        new = [r for r in removals if (r['model_key'], r['project_id']) not in have]
        if new:
            pc.s3c().put_object(Bucket=pc.BUCKET, Key=f'{pc.PSTATE}/removals_pending.jsonl',
                                Body=prev + ''.join(json.dumps(r) + '\n' for r in new).encode(), ContentType='application/x-ndjson')
        pc.put_json(pc.BUCKET, f'{pc.PSTATE}/status.json', status)
    return jobs, status


def ad_index_key(ad):
    return sys.modules[type(ad).__module__].INDEX


def cmd_delta(a):
    if a.write: must_write()
    jobs, st = pkg_delta(a.adapter, write=a.write)
    print(json.dumps(st, indent=1)); print(f'{len(jobs)} jobs')


def cmd_verify(a):
    ad = load_adapter(a.adapter)
    rows = ad.conv_rows()
    shipped, targets, refs, nots, why, unknown = shipped_by_project(ad, rows)
    keys = {r['id']: r['step_key'] for r in shipped.values()}
    pids = a.projects.split(',') if a.projects else [p.rstrip('/').rsplit('/', 1)[-1] for p in
                                                       _prefixes(f'{pc.DATASET}/{pc.ROUTE}/')]
    out = [pc.verify_project(pc.BUCKET, p, keys, full_hash=a.full_hash) for p in pids]
    agg = collections.Counter()
    for v in out: agg.update(v['checks'])
    print(json.dumps({'projects': len(out), 'ok': sum(v['ok'] for v in out), 'checks': dict(agg)}, indent=1))


def _prefixes(prefix):
    out = []; tok = None
    while True:
        kw = {'Bucket': pc.BUCKET, 'Prefix': prefix, 'Delimiter': '/'}
        if tok: kw['ContinuationToken'] = tok
        r = pc.s3c().list_objects_v2(**kw)
        out += [c['Prefix'] for c in r.get('CommonPrefixes') or []]
        if not r.get('IsTruncated'): return out
        tok = r['NextContinuationToken']


def main():
    p = argparse.ArgumentParser(); sp = p.add_subparsers(dest='cmd', required=True)
    x = sp.add_parser('plan'); x.add_argument('--adapter', default='zen3'); x.add_argument('--projects'); x.add_argument('--job-ids')
    x.add_argument('--all', action='store_true'); x.add_argument('--out', default='plans'); x.add_argument('--cache-dir')
    x.add_argument('--index'); x.add_argument('--policy'); x.add_argument('--shard', help='i/N'); x.add_argument('--gz', action='store_true')
    x.set_defaults(f=cmd_plan)
    x = sp.add_parser('job'); x.add_argument('--job', required=True); x.add_argument('--workdir', default='/tmp/pkgwork'); x.set_defaults(f=cmd_job)
    x = sp.add_parser('delta'); x.add_argument('--adapter', default='zen3'); x.add_argument('--write', action='store_true'); x.set_defaults(f=cmd_delta)
    x = sp.add_parser('verify'); x.add_argument('--adapter', default='zen3'); x.add_argument('--projects'); x.add_argument('--full-hash', action='store_true')
    x.set_defaults(f=cmd_verify)
    x = sp.add_parser('build-d4-index'); x.add_argument('--procs', type=int, default=32)
    x.set_defaults(f=lambda a: (must_write(), sys.modules[type(load_adapter('zen3')).__module__].build_d4_index(a.procs, log)))
    x = sp.add_parser('compact'); x.set_defaults(f=lambda a: (must_write(), pc.compact_ledger(pc.BUCKET, write=True)))
    a = p.parse_args(); a.f(a)


if __name__ == '__main__':
    main()
