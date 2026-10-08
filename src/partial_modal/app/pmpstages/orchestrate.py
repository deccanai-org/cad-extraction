"""per-model orchestrator: source -> pipeline -> issues (+package +bundle) -> bundle upload, with retries, class
escalation on memory kills, and every failure recorded (never silently skipped). Pure Python: the stage calls are
injected (Modal functions' .remote in modal_app.run_model), so the logic is unit-testable without Modal.

Index row (one per model and run; /vol/index/<run>/<model_id>.json, merged into /vol/index/<run>.jsonl):
  model_id, pid, tag, model_folder, step, source_kind, bytes, cls (started) / cls_final, status, error, stages{...},
  bundle{path, bytes, sha256}, upload{object, ok, etag ...}, seconds, started, finished, run
status: done (bundle uploaded) | bundled (no PUT URL in the job, or --no-upload) | upload_failed | issues_failed |
        pipeline_failed | source_failed | too_big_v1 | not_runnable:<why> | error
"""
import json, os, time, traceback

from . import common as C

HOST_DRAWS = 8             # source calls while the stage reports host_unsuitable (AVX2-only host; a new container each)
INFRA_RETRIES = 2          # re-calls of a stage whose container died (preemption, crash, OOM of the whole container)


def _call(fn, args, log, what, retries=INFRA_RETRIES):
    """call a remote stage; an exception = the container / platform failed (stages catch their own errors) ->
    retried with back-off; returns (result or None, [errors]). Each call gets its own token in job['_call'] (first
    argument, when it is the job dict): the stage records its container starts under it (common.record_start), so a
    preemption restart inside one call is counted, never hidden."""
    errs = []
    for i in range(retries + 1):
        a = args
        if args and isinstance(args[0], dict):
            a = (dict(args[0], _call=f'{what.replace(" ", "/")}/{i + 1}/{time.time_ns()}'),) + tuple(args[1:])
        try:
            return fn(*a), errs
        except Exception as e:
            msg = f'{type(e).__name__}: {str(e)[:500]}'
            errs.append(msg)
            log(f'{what}: attempt {i + 1} raised {msg}')
            if 'Timeout' in type(e).__name__:
                break           # a Modal timeout repeats deterministically: the class decides, not a retry
            time.sleep(min(120, 15 * (i + 1)))
    return None, errs


def orchestrate(job_raw, run_name, opts, F, write_row, log=print):
    """job_raw: a job row (with URLs). opts: {'upload': bool, 'escalate': bool, 'skip_done': bool}.
    F: {'source': {kind: {cls: callable(job, cls, run)}}, 'pipeline': {cls: callable(job, cls, ifc_spec, run)},
        'issues': {cls: callable(job, cls, run)}, 'upload': callable(model_id, run, put_url, headers)}
    write_row(row): persists the index row (called at the end; also after each stage for progress)."""
    t0 = time.time()
    row = {'run': run_name, 'model_id': job_raw.get('id') or job_raw.get('model_id'), 'tag': job_raw.get('tag'),
           'pid': job_raw.get('pid'), 'status': 'error', 'error': None, 'stages': {},
           'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        job = C.normalise_job(job_raw)
        row.update(model_id=job['id'], model_folder=job['model_folder'], step=job['step'], source_kind=job['source_kind'],
                   bytes=job['bytes'], cls=job['cls'], code=job['code_version'])
        ok, why = C.job_runnable(job)
        if not ok:
            row.update(status='too_big_v1' if why == 'too_big_v1' else f'not_runnable:{why}', error=why)
            return _finish(row, t0, write_row)
        cls = job['cls']
        # ---- 1. source
        kind = job['source_kind']
        if kind == 'package_ifc':
            ifc_spec = {'mode': 'package', 'url_key': 'ifc'}
        else:
            fn = (F['source'].get(kind) or {}).get(cls)
            if fn is None:
                row['stages']['source'] = {'ok': False, 'error': f'plugin_image_missing for {kind}'}
                row.update(status='source_failed', error=f'no source stage deployed for {kind}')
                return _finish(row, t0, write_row)
            draws, all_errs = [], []
            for d in range(HOST_DRAWS):
                r, errs = _call(fn, (job, cls, run_name), log, f'{job["id"][:12]} source')
                all_errs += errs
                hu = bool(r) and not r.get('ok') and (r.get('verdict') == 'host_unsuitable' or r.get('retryable'))
                draws.append({'draw': d + 1, 'ok': bool(r and r.get('ok')), 'verdict': (r or {}).get('verdict'),
                              'host_cpu': (r or {}).get('host_cpu'), 'seconds': (r or {}).get('seconds'),
                              'cpu_seconds': (r or {}).get('cpu_seconds')})
                if not hu:
                    break
                log(f'{job["id"][:12]} source draw {d + 1}: host_unsuitable -> new container')
            row['stages']['source'] = r or {'ok': False, 'error': 'stage crashed: ' + '; '.join(all_errs)}
            row['stages']['source']['host_draws'] = draws
            row['stages']['source']['attempts'] = len(draws)
            row['stages']['source']['cpu_seconds_all_draws'] = round(sum(x.get('cpu_seconds') or 0 for x in draws), 1)
            if all_errs:
                row['stages']['source']['infra_errors'] = all_errs
            if not (r and r.get('ok')):
                row.update(status='source_failed', error=row['stages']['source'].get('error'))
                return _finish(row, t0, write_row)
            ifc_spec = {'mode': 'volume', 'path': r['ifc_path'], 'sha256': r['sha256']}
            job['ifc'] = r['ifc']           # the regenerated / emitted IFC's name in /<id>/source/ (pipeline, issues, package)
            write_row(dict(row, status='running:pipeline'))
        # ---- 2. pipeline (one escalation to the next class when a step was memory-killed or the container died)
        attempts = []
        while True:
            r, errs = _call(F['pipeline'][cls], (job, cls, ifc_spec, run_name), log, f'{job["id"][:12]} pipeline {cls}')
            att = r or {'ok': False, 'error': 'stage crashed: ' + '; '.join(errs)}
            if errs:
                att['infra_errors'] = errs
            att['cls'] = cls
            attempts.append(att)
            nxt = C.next_class(cls)
            oom = bool(att.get('memory_killed_steps')) or (r is None and any('OOM' in e or 'memory' in e.lower() for e in errs))
            if opts.get('escalate', True) and nxt and oom and len(attempts) < 3:
                log(f'{job["id"][:12]} pipeline memory-killed at {cls} -> retry at {nxt}')
                cls = nxt
                continue
            break
        row['stages']['pipeline'] = attempts[-1]
        if len(attempts) > 1:
            row['stages']['pipeline_attempts'] = [{k: a.get(k) for k in ('cls', 'ok', 'error', 'memory_killed_steps', 'seconds')}
                                                  for a in attempts]
        row['cls_final'] = cls
        if not attempts[-1].get('ok'):
            row.update(status='pipeline_failed', error=attempts[-1].get('error'))
            return _finish(row, t0, write_row)
        write_row(dict(row, status='running:issues'))
        # ---- 3. issues + package + bundle
        r, errs = _call(F['issues'][cls], (job, cls, run_name), log, f'{job["id"][:12]} issues {cls}')
        row['stages']['issues'] = r or {'ok': False, 'error': 'stage crashed: ' + '; '.join(errs)}
        if errs:
            row['stages']['issues']['infra_errors'] = errs
        if not (r and r.get('ok')):
            row.update(status='issues_failed', error=row['stages']['issues'].get('error'))
            return _finish(row, t0, write_row)
        row['bundle'] = {k: r['bundle'].get(k) for k in ('path', 'bytes', 'sha256', 'md5')}
        # ---- 4. upload
        if not opts.get('upload', True) or not job.get('put_url'):
            row.update(status='bundled', error=None if opts.get('upload', True) is False else 'no put_url in the job')
            return _finish(row, t0, write_row)
        u, errs = _call(F['upload'], (job['id'], run_name, job['put_url'], job.get('put_headers') or {}), log,
                        f'{job["id"][:12]} upload')
        row['upload'] = u or {'ok': False, 'error': 'stage crashed: ' + '; '.join(errs)}
        row.update(status='done' if row['upload'].get('ok') else 'upload_failed',
                   error=None if row['upload'].get('ok') else row['upload'].get('error'))
    except Exception as e:
        row.update(status='error', error=f'{type(e).__name__}: {e}', traceback=traceback.format_exc()[-3000:])
    return _finish(row, t0, write_row)


def _finish(row, t0, write_row):
    row['seconds'] = round(time.time() - t0, 1)
    row['finished'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    st = row.get('stages') or {}
    row['cpu_seconds'] = round(sum((st.get(k) or {}).get('cpu_seconds') or 0 for k in ('source', 'pipeline', 'issues')), 1)
    row['peak_gib'] = max([(st.get(k) or {}).get('peak_gib') or 0 for k in ('source', 'pipeline', 'issues')] or [0])
    # container restarts after preemption (the stage's cpu_seconds cover only the last, completed start)
    row['container_restarts'] = sum(max(0, ((st.get(k) or {}).get('container_starts') or 1) - 1) for k in ('source', 'pipeline', 'issues'))
    try:
        write_row(row)
    except Exception as e:
        row['index_write_error'] = repr(e)
    return row
