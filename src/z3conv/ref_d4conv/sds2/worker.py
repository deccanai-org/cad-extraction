#!/usr/bin/env python3
"""Zentitude-data-4 SDS/2 job folder -> STEP worker (fleet kit, one process per host).

Job list  _control/conv/sds2/jobs.json   (one job per distinct SDS/2 job-folder content; files = stored data-4 keys)
Output    conversions/sds2-step/<job id>/<name>_stage2.step (+ _pieces.csv, _skipped.csv, _members.csv, _preview.png,
          _stage2.log, job.json)          accepted outputs only (run-2 rule, below)
          conversions/sds2-step/_not_accepted/<job id>/...   STEP written but not accepted (kept for diagnosis)
Result    _state/conv/sds2/results/<job id>.json

Converter = the pipeline run 2 accepted results with: sds2-step-pipeline-v4-candidate.zip
(sha256 c5b65d271d3a6c69853d745d705cbb92b431e8891686068e7a555e720b3c15f0), same per-job command as its
batch/run_batch.py with --no-fallback --timeout 14400:  sds2_to_step.py <job> -o <name>_stage2.step --stage 2 --verify
(verify = OCC read-back: solid count, BRep validity, bbox). Only the job's main/ mem/ subm/ files are materialized
(what run_batch extracts; SDS/2 folder/index names lower-cased). QA verdict = run_batch.qa() unchanged.
Accepted (= run-2 audit "full stage-2 verified + uploaded"): status ok, stage-2 rc 0, qa pass|warn, verification
counts present, 0 invalid solids (valid == solids > 0), outputs uploaded.
"""
import os, sys, re, json, time, shutil, hashlib, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf

CODE = 'z4-sds2-v4-2026-09-30b'
# b: runtime convfleet-v4 (redo entries in _control/conv/sds2/redo_ids.json, e.g. download_error requeue after the extraction repair)
OUT = cf.ROOT + '/conversions/sds2-step'
W = os.environ.get('CONV_HOME', '/opt/conv')
PY = os.path.join(W, 'sds2env/bin/python')              # python 3.12 + cadquery-ocp 8.0.1 (pipeline requirements.txt)
PIPE = os.path.join(W, 'sds2-v4/sds2-step-pipeline')
TIMEOUT = int(os.environ.get('SDS2_TIMEOUT_S', '14400'))
FILES = ('worker.py', 'convfleet.py', 'fetch.py', 'sds2-step-pipeline-v4-candidate.zip')
DIRS = ('main', 'mem', 'subm')

ZIP_SHA = 'c5b65d271d3a6c69853d745d705cbb92b431e8891686068e7a555e720b3c15f0'


def ensure_pipeline():
    """unpack the verified v4 zip once (setup.sh does it too; this covers a hot-reloaded kit)"""
    mark = os.path.join(W, 'sds2-v4', '.zip_sha256')
    if os.path.exists(os.path.join(PIPE, 'decode', 'sds2_to_step.py')) and os.path.exists(mark) and open(mark).read().strip() == ZIP_SHA:
        return
    z = os.path.join(HERE, 'sds2-step-pipeline-v4-candidate.zip')
    h = cf.sha256_file(z)
    if h != ZIP_SHA:
        raise SystemExit(f'pipeline zip sha256 {h} != {ZIP_SHA}')
    import zipfile
    zipfile.ZipFile(z).extractall(os.path.join(W, 'sds2-v4'))
    open(mark, 'w').write(ZIP_SHA)


ensure_pipeline()
_spec = importlib.util.spec_from_file_location('run_batch', os.path.join(PIPE, 'batch', 'run_batch.py'))
RB = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(RB)   # parse_log, qa, error_class, safe, CANON


def load_files(job):
    """model files of the chosen job root (main/ mem/ subm/), written by the job-list builder:
    [{p: path relative to the job folder, sha256, size, key | disk12}]"""
    import gzip
    body = cf.s3.get_object(Bucket=cf.B, Key=job['files_key'])['Body'].read()
    try:
        body = gzip.decompress(body)
    except OSError:
        pass                                   # boto3 may already have decoded Content-Encoding: gzip
    return json.loads(body)


def need_bytes(job):
    return max(4 << 30, (job.get('model_bytes') or 0) * 8)     # README: a conversion peaks at ~3-4 GB while verifying


def conv_env():
    # conda python 3.12's pyexpat needs its own newer libexpat; the system libfontconfig (pulled in by the OCP wheel)
    # would otherwise bind the soname to the distro's older copy (undefined symbol XML_SetAllocTrackerActivationThreshold)
    env = dict(os.environ, PYTHONUNBUFFERED='1', MPLBACKEND='Agg')
    ex = os.path.join(W, 'sds2env', 'lib', 'libexpat.so.1')
    if os.path.exists(ex):
        env['LD_PRELOAD'] = ex
    return env


def tail_of(p, n=2000):
    try:
        return open(p, errors='replace').read()[-n:]
    except Exception:
        return ''


def parse_bbox(txt):
    m = re.search(r'model bbox \(in\): min \[([^\]]*)\] max \[([^\]]*)\]', txt)
    if not m:
        return None
    try:
        lo = [float(x) for x in m.group(1).split()]; hi = [float(x) for x in m.group(2).split()]
        return lo + hi if len(lo) == 3 and len(hi) == 3 else None
    except ValueError:
        return None


def process(fl, job, d):
    jid = job['id']
    rec = {'name': job.get('name'), 'n_files': job.get('n_files'), 'paths_sample': job.get('paths', [])[:3], 'n_paths': len(job.get('paths', [])),
           'disk2_run2_match': job.get('disk2_run2_match'), 'pipeline': 'sds2-step-pipeline v4 (run-2 accepted): sds2_to_step.py --stage 2 --verify, --no-fallback'}
    root = job.get('job_root'); rec['job_roots'] = (job.get('job_roots') or [])[:10]
    if root is None:
        return dict(rec, status='fail', reason='job_folder_incomplete',
                    detail='no main/jsetup anywhere in the job folder (no SDS/2 model data: main/ and mem/ absent)')
    rec['job_root'] = root
    mf = load_files(job)
    d12 = [f for f in mf if f.get('disk12')]; miss = [f for f in mf if not f.get('key') and not f.get('disk12') and f['size'] > 0]
    rec['model_files'] = len(mf); rec['model_bytes'] = sum(f['size'] for f in mf); rec['model_files_disk12'] = len(d12)
    if miss or d12:
        return dict(rec, status='fail', reason='model_files_unavailable', detail=f'{len(miss)} unresolved + {len(d12)} disk12-only model files',
                    sample=[f['p'] for f in (miss + d12)[:10]])
    name = RB.safe(os.path.basename(root) if root else (job.get('name') or 'job')) + '_' + jid[:6]
    jobdir = os.path.join(d, 'job', name)
    pre_len = len(root) + 1 if root else 0
    items = []
    for f in mf:
        rel = f['p'].replace('\\', '/')[pre_len:]
        parts = [p.lower() if p.lower() in RB.CANON else p for p in rel.split('/') if p]
        items.append([f.get('key'), os.path.join(jobdir, *parts), f['size']])
    lst = os.path.join(d, 'fetch.json'); json.dump(items, open(lst, 'w'))
    rc, out, err = fl.sh([PY, os.path.join(HERE, 'fetch.py'), lst, '48'], timeout=7200)
    try:
        fr = json.loads(out.strip().splitlines()[-1])
    except Exception:
        return dict(rec, status='fail', reason='download_error', transient=True, error=(err or out)[-400:])
    rec['fetch'] = {k: fr.get(k) for k in ('n', 'bytes', 'n_errors', 'sec')}
    if fr.get('n_errors'):
        return dict(rec, status='fail', reason='download_error', transient=True, error=fr.get('errors'))
    if not RB.is_job(jobdir):
        return dict(rec, status='fail', reason='job_folder_incomplete', detail='main/job_mtrl or mem/mem_idx missing')
    ver = RB.read_version(jobdir); rec['version'] = ver
    outdir = os.path.join(d, 'out'); os.makedirs(outdir, exist_ok=True)
    step = os.path.join(outdir, f'{name}_stage2.step'); logf = os.path.join(d, 'convert.log')
    t = time.time()
    rc = fl.run(jid, [PY, '-u', os.path.join(PIPE, 'decode', 'sds2_to_step.py'), jobdir, '-o', step, '--stage', '2', '--verify'],
                logf, TIMEOUT, env=conv_env(), cwd=outdir)
    if rc == -9:
        raise MemoryError()
    txt = open(logf, errors='replace').read()
    keep = '\n'.join(l for l in txt.splitlines() if not l.startswith('*') and 'Transferr' not in l and l.strip() and not l.startswith('$ '))
    open(os.path.join(outdir, f'{name}_stage2.log'), 'w', encoding='utf-8').write(keep)
    s2 = RB.parse_log(txt)
    s2.update(rc='timeout' if rc in (124, 125) else rc, wall_s=round(time.time() - t),
              step_mb=round(os.path.getsize(step) / 2 ** 20, 1) if os.path.exists(step) else None)
    if rc != 0:
        s2['error'] = keep[-400:]
    r2 = {'status': 'ok' if rc == 0 else 'failed', 'stage2': s2, 'version': ver}
    q, why = RB.qa(r2)
    rec.update(stage2=s2, run_status=r2['status'], qa=q, qa_reasons=why)
    bbox_in = parse_bbox(txt)
    solids, valid = s2.get('solids'), s2.get('valid')
    readback = solids is not None and valid is not None
    rec['validate'] = {'read_status': 'ok' if readback else None, 'solids': solids, 'valid': valid, 'invalid': (solids - valid) if readback else None,
                       'bbox_in': bbox_in, 'bbox_mm': [round(v * 25.4, 1) for v in bbox_in] if bbox_in else None,
                       'steel_ratio': s2.get('steel_ratio'), 'validated': bool(readback and solids and valid == solids),
                       'by': 'pipeline decode/verify_step.py (OCP read-back: BRepCheck_Analyzer per shape, volume, bbox)'}
    accepted = (r2['status'] == 'ok' and s2.get('rc') == 0 and q != 'fail' and readback and solids > 0 and valid == solids
                and os.path.exists(step))
    if accepted and bbox_in and not cf.bbox_sane([v * 25.4 for v in bbox_in]):
        accepted = False; rec['bbox_insane'] = True
    files = [f for f in os.listdir(outdir)]
    has_step = os.path.exists(step) and os.path.getsize(step) > 0
    if has_step:
        prefix = f'{OUT}/{jid}' if accepted else f'{OUT}/_not_accepted/{jid}'
        meta = {'id': jid, 'name': job.get('name'), 'version': ver, 'job_root': root, 'paths': job.get('paths'), 'qa': q, 'qa_reasons': why,
                'accepted': accepted, 'stage2': s2, 'validate': rec['validate'], 'code': CODE, 'converted': cf.now()}
        json.dump(meta, open(os.path.join(outdir, 'job.json'), 'w'), default=str)
        files = sorted(os.listdir(outdir))
        for f in files:
            fl.upload(os.path.join(outdir, f), f'{prefix}/{f}', 'application/step' if f.endswith('.step') else None)
        rec['outputs'] = {'prefix': prefix + '/', 'files': files}
    rec['accepted'] = accepted
    if accepted:
        rec['step'] = {'key': f'{OUT}/{jid}/{name}_stage2.step', 'files': 1, 'bytes': os.path.getsize(step), 'solids': solids,
                       'bbox_mm': rec['validate']['bbox_mm'], 'version': ver}
        rec['status'] = 'ok'
        return rec
    if r2['status'] != 'ok':
        reason = RB.error_class(r2)
        reason = {'timeout': 'timeout', 'STEP write failed': 'step_write_failed', 'missing job file': 'missing_job_file',
                  'out of memory': 'out_of_memory'}.get(reason, re.sub(r'[^a-z0-9]+', '_', reason.lower()).strip('_') or 'convert_error')
        if 'too few members to calibrate' in txt:
            reason = 'no_members_to_calibrate'
        elif 'unsupported job_mtrl layout' in txt:
            reason = 'unsupported_job_mtrl_layout'
    elif not readback:
        reason = 'verification_counts_missing'
    elif valid != solids:
        reason = 'invalid_solids'
    elif q == 'fail':
        reason = 'qa_fail'
    elif rec.get('bbox_insane'):
        reason = 'absurd_bbox'
    else:
        reason = 'not_accepted'
    return dict(rec, status='fail', reason=reason, log_tail=keep[-1500:])


if __name__ == '__main__':
    os.environ.setdefault('CONV_SLOTS', str(max(1, min((os.cpu_count() or 4) - 2, (cf.mem()[0] >> 30) // 6))))
    fl = cf.Fleet('sds2', CODE, process, need_bytes, FILES, redo_ids_key=f'{cf.ROOT}/_control/conv/sds2/redo_ids.json')
    sys.exit(fl.main())
