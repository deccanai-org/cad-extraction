"""stage.py - the issues plug-in entry point (contract of app/pmpstages/plugins.py: run(job, ctx) -> dict).

Runs make_issues.py for ONE model inside the pipeline image (python + issues_lib only, no CAD kernel):
  inputs   ctx['pipeline_out'] (schedules + verification.csv of our pipeline), ctx['step_path'] (the delivered STEP),
           ctx['source_dir'] (/<id>/source/: skipped_records.json from src_db1, sds2_facts.json from src_sds2), and the
           conversion detail files of the job (pre-signed GET URLs urls['detail/<alias>'] -> downloaded under their S3
           key basenames, the names make_issues.py looks for: *.parts.json, *.check.json, <id>.json, *src_parts.jsonl.gz,
           *step_parts.jsonl.gz, *decoded_parts.json.gz, <stem>_pieces.csv, <stem>_skipped.csv, <stem>.log)
  outputs  ctx['out']/schedules/issues.json, ctx['out']/schedules/missing_parts.json, ctx['out']/issues/WHERE_TO_LOOK.md
Returns {'ok', 'error', 'counts' (rebuild-mode colour counts = what build_issues_model.py must write),
         'counts_delivered', 'missing', 'flagged', 'not_drawn', 'detail_files', 'maker_stdout'}.
A detail file that cannot be downloaded is recorded (never silently ignored); make_issues.py then records the checks it
could not evaluate in issues.json (checks[].status = not_evaluated).
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))

# job keys make_issues.py reads (the rest of the job row - URLs included - never reaches it)
JOB_KEYS = ('model_id', 'pid', 'relpath', 'step_source', 'converter', 'converted_from', 'converted_from_package', 'partial',
            'partial_kind', 'grader', 'verify_codes', 'verify_verdict', 'model_folder', 'pin', 'problems', 'severity', 'tag',
            'addon', 'n_models_in_pkg')


def run(job, ctx):
    log = ctx.get('log') or print
    work = ctx['work']
    out = ctx['out']
    conv = os.path.join(work, 'conv')
    os.makedirs(conv, exist_ok=True)
    # ---- the job row make_issues.py reads (URL-free)
    jr = {k: job.get(k) for k in JOB_KEYS if job.get(k) is not None}
    jr['model_id'] = job.get('model_id') or job.get('id')
    jr['relpath'] = job.get('relpath') or (job.get('step') if isinstance(job.get('step'), str) else None)
    if not jr['relpath']:
        return {'ok': False, 'error': 'job without relpath (the delivered STEP inside the package)'}
    jr['model_folder'] = ctx.get('model_folder') or job.get('model_folder')
    convinfo = job.get('conv') or {}
    if convinfo.get('step_key'):
        jr['step_key'] = convinfo['step_key']           # SDS/2: the converter's side tables are named after this stem
    jf = os.path.join(work, 'job.json')
    with open(jf, 'w') as f:
        json.dump(jr, f, indent=1, sort_keys=True, default=str)
    # ---- conversion detail files (only those proven to come from the shipped conversion run: the jobs component
    #      signs only those)
    detail_keys = job.get('detail_keys') or {}
    files, missing = {}, {}
    for uk in sorted(k for k in (job.get('urls') or {}) if k.startswith('detail/')):
        alias = uk.split('/', 1)[1]
        key = detail_keys.get(alias)
        name = os.path.basename(key) if key else f'{jr["model_id"]}.{alias}'
        if not name or name.startswith('.') or '/' in name:
            missing[alias] = f'unsafe file name {name!r}'
            continue
        try:
            r = ctx['fetch'](uk, os.path.join(conv, name))
            files[alias] = {'name': name, 'bytes': r.get('bytes'), 'sha256': r.get('sha256'), 'object': r.get('object')}
        except Exception as e:
            missing[alias] = f'{type(e).__name__}: {str(e)[:300]}'
            log(f'detail/{alias} not downloaded: {missing[alias]}')
    src = ctx.get('source_dir') or ''
    db1_facts = os.path.join(src, 'skipped_records.json')
    sds2_facts = os.path.join(src, 'sds2_facts.json')
    out_sched, out_issues = os.path.join(out, 'schedules'), os.path.join(out, 'issues')
    cmd = [sys.executable, os.path.join(HERE, 'make_issues.py'), '--job', jf, '--sched', ctx['pipeline_out'],
           '--delivered', ctx['step_path'], '--out-sched', out_sched, '--out-issues', out_issues, '--conv', conv,
           '--model-name', jr['model_folder'], '--source-ifc', ctx.get('ifc_path') or '']
    if os.path.isfile(db1_facts):
        cmd += ['--db1-facts', db1_facts]
    if os.path.isfile(sds2_facts):
        cmd += ['--sds2-facts', sds2_facts]
    log('make_issues: ' + ' '.join(os.path.basename(c) if c.startswith('/') else c for c in cmd[1:]))
    p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=(max(300, int(ctx['deadline'] - time.time())) if ctx.get('deadline') else 3600),
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    for line in (p.stdout + p.stderr).splitlines()[-60:]:
        log('make_issues| ' + line[:500])
    rec = {'ok': False, 'error': None, 'detail_files': files, 'detail_missing': missing, 'maker_rc': p.returncode,
           'maker_stdout': p.stdout[-4000:]}
    if p.returncode != 0:
        rec['error'] = f'make_issues.py rc {p.returncode}: {(p.stdout + p.stderr)[-1500:]}'
        return rec
    try:
        iss = json.load(open(os.path.join(out_sched, 'issues.json')))
    except Exception as e:
        rec['error'] = f'issues.json not readable: {e}'
        return rec
    rec.update(ok=True, counts=iss['counts']['rebuild'], counts_delivered=iss['counts']['delivered'],
               missing=len(iss.get('missing') or []), flagged=len(iss.get('parts') or {}),
               not_drawn=len(iss.get('not_drawn') or []), categories=iss.get('categories'),
               reconciliation=iss.get('reconciliation'),
               checks_not_evaluated=[c.get('check') for c in (iss.get('checks') or []) if c.get('status') != 'evaluated'])
    return rec
