"""Unit test of the issues component on Modal, on the NEW samples only (n1..n5; default n1 + n5).

    cd /Users/dhiren/Downloads/Deccan/partial_modal
    .venv/bin/modal run issues/tests/modal_unit.py                       # n1_db1_small + n5_sds2
    .venv/bin/modal run issues/tests/modal_unit.py --tags n5_sds2        # one sample

Per model, in one container of the pipeline image (pinned requirements + system libs + code variants + issues/ + app/):
  1. inputs: the pipeline output of this model on the volume (/<id>/pipeline/out, else /_unit/issues/<id>/pipeline/out);
     when there is none, the app's pipeline stage (pmpstages.pipeline.run, unchanged) is run on the source IFC the
     source stage left on the volume (/<id>/source/ or /_unit/src_db1/<id>/source/), with its outputs under
     /_unit/issues/<id>/ (never the canonical /<id>/ folders); no source IFC -> the model is reported 'blocked'
  2. issues/stage.py run(job, ctx) = make_issues.py -> schedules/issues.json, missing_parts.json, issues/WHERE_TO_LOOK.md
  3. a package-shaped tree (scripts/steelbuild.py, scripts/issues_lib.py, scripts/<model>/build_model.py,
     build_issues_model.py, schedules/, the delivered STEP at its package path) and THE SHIPPED SCRIPT run from it as a
     user runs it: default (--jobs J --verify), again in a fresh copy (--jobs 1: byte-identical files required),
     --from-delivered --verify (text check: geometry statements unchanged + colours; XCAF read-back), --list
  4. counts checked: build_issues_model.py's written / read-back counts = issues.json; issues.json reconciled against
     the partial record (every row carries its explanation)
Results: /vol/_unit/issues/<id>/ (+ pulled to issues/tests/results/<tag>/). Pre-signed URLs are never printed or saved.
"""
import json, os, pathlib, sys, time

import modal

HERE = pathlib.Path(__file__).resolve().parent            # issues/tests
COMP = HERE.parent                                        # issues
ROOT = COMP.parent                                        # partial_modal
SIGNED = ROOT / 'jobs' / 'urls' / 'new5.signed.jsonl'
NEW5 = ROOT / 'new5.json'
FORBIDDEN = ROOT / 'app' / 'forbidden_ids.json'
SYS_LIBS = ['libgl1', 'libxrender1', 'libxext6', 'libsm6', 'libfontconfig1', 'libxkbcommon0', 'libxi6']
VARIANTS = ('code_v9a', 'code_db1b', 'code_sds2')
SKIP_DIRS = {'__pycache__', 'tests', 'results', '.git', 'test_out', 'logs', 'presigned'}

app = modal.App('pmp-issues-unit')
vol = modal.Volume.from_name('pmp-out', create_if_missing=False)


def _ign(base):
    def ign(p):
        p = pathlib.Path(p)
        if set(p.parts) & SKIP_DIRS or any(x.startswith('.') for x in p.parts):
            return True
        return p.suffix.lower() in ('.pyc', '.step', '.stp', '.ifc', '.gz', '.zip', '.log', '.png')
    return ign


def _image():
    img = (modal.Image.debian_slim(python_version='3.11')
           .apt_install(*SYS_LIBS)
           .pip_install_from_requirements(str(ROOT / 'code' / 'requirements.txt'))
           .env({'PYTHONUNBUFFERED': '1', 'OMP_NUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}))
    for v in VARIANTS:
        img = img.add_local_dir(ROOT / 'code' / v, f'/pmp/code/{v}', ignore=_ign(ROOT / 'code' / v))
    img = img.add_local_file(ROOT / 'code' / 'requirements.txt', '/pmp/code/requirements.txt')
    img = img.add_local_dir(ROOT / 'app', '/pmp/app', ignore=_ign(ROOT / 'app'))
    img = img.add_local_dir(COMP, '/pmp/issues', ignore=_ign(COMP))
    return img


IMAGE = _image() if modal.is_local() else modal.Image.debian_slim(python_version='3.11')
SCHEDULE_FILES = ('parts.csv', 'profiles.csv', 'profile_outlines.json', 'solids.csv', 'cuts.csv', 'cut_boundaries.json',
                  'openings.csv', 'paths.json', 'exact_geometry.jsonl', 'assemblies.csv')


@app.function(image=IMAGE, cpu=4.0, memory=24 * 1024, timeout=4 * 3600, volumes={'/vol': vol}, max_containers=5)
def unit(job: dict, forbidden: list, run_pipeline: bool = True):
    import glob, hashlib, re, shutil, subprocess, traceback
    sys.path.insert(0, '/pmp/app')
    from pmpstages import common as C
    T0 = time.time()
    J = 8
    PY = sys.executable
    job = C.normalise_job(job)
    ID = job['id']
    if any(ID.startswith(f[:16]) for f in forbidden):
        return {'ok': False, 'error': 'refused: one of the original 5 samples'}
    UD = f'/vol/_unit/issues/{ID}'
    res = {'model_id': ID, 'tag': job.get('tag'), 'step_source': job.get('step_source'), 'steps': {}, 'checks': {}}
    W = f'/tmp/iu/{ID[:16]}'
    shutil.rmtree(W, ignore_errors=True)
    os.makedirs(W)
    logp = os.path.join(W, 'unit.log')

    def log(msg):
        with open(logp, 'a') as f:
            f.write(time.strftime('%H:%M:%S ') + str(msg) + '\n')
        print(f'[{ID[:12]}] {msg}', flush=True)

    def sha(p):
        h = hashlib.sha256()
        with open(p, 'rb') as f:
            for b in iter(lambda: f.read(1 << 22), b''):
                h.update(b)
        return h.hexdigest()

    def run(cmd, cwd, name, timeout=3 * 3600):
        t0 = time.time()
        p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        with open(os.path.join(W, f'{name}.out'), 'w') as f:
            f.write(p.stdout)
        res['steps'][name] = dict(rc=p.returncode, seconds=round(time.time() - t0, 1), tail=p.stdout[-2500:])
        log(f'{name}: rc {p.returncode} {time.time() - t0:.0f}s')
        return p.returncode, p.stdout

    try:
        vol.reload()
        # ---------------------------------------------------------------- source stage output (IFC + side tables)
        src_dir, ifc = None, None
        for d in (f'/vol/{ID}/source', f'/vol/_unit/src_db1/{ID}/source', f'/vol/_unit/src_sds2/{ID}/source'):
            if not os.path.isdir(d):
                continue
            cand = sorted(glob.glob(os.path.join(d, '*.ifc')))
            prov = C.read_json(os.path.join(d, 'provenance.json'), {}) or {}
            if cand:
                src_dir, ifc = d, cand[0]
                res['source'] = dict(dir=d, ifc=os.path.basename(ifc), ifc_sha256=sha(ifc), verdict=prov.get('verdict'),
                                     files=sorted(os.listdir(d)))
                break
            if src_dir is None:
                src_dir = d                         # side tables without an IFC (e.g. a source stage that did not reproduce)
        if job['source_kind'] == 'package_ifc':
            res['blocked'] = 'package-IFC models are not part of this unit test (n1 / n5)'
            return res
        # ---------------------------------------------------------------- pipeline output
        PO = None
        for d in (f'/vol/{ID}/pipeline', f'{UD}/pipeline'):
            if os.path.exists(os.path.join(d, 'out', 'verification.csv')) and os.path.exists(os.path.join(d, 'summary.json')):
                PO = d
                break
        if PO is None:
            if not ifc:
                res['blocked'] = (f'no pipeline output and no source IFC on the volume yet (source stage dirs: '
                                  f'{src_dir or "none"}): the source stage must reproduce the shipped STEP first')
                return res
            if not run_pipeline:
                res['blocked'] = 'no pipeline output on the volume (run_pipeline off)'
                return res
            from pmpstages import pipeline
            C.VOL = '/vol/_unit/issues'               # outputs under /_unit/issues/<id>/, never the canonical folders
            log(f'running the app pipeline stage on {os.path.basename(ifc)}')
            pr = pipeline.run(job, {'mode': 'volume', 'path': ifc, 'sha256': res['source']['ifc_sha256']}, job['cls'],
                              time.time() + 3 * 3600)
            C.VOL = '/vol'
            vol.commit()
            res['pipeline_run'] = {k: pr.get(k) for k in ('ok', 'perfect', 'reasons', 'status', 'parts', 'steps',
                                                          'step_seconds', 'seconds', 'error')}
            PO = f'{UD}/pipeline'
            if not os.path.exists(os.path.join(PO, 'out', 'verification.csv')):
                res['error'] = 'the pipeline stage wrote no verification.csv'
                return res
        summ = C.read_json(os.path.join(PO, 'summary.json'), {})
        res['pipeline'] = dict(dir=PO, perfect=summ.get('perfect'), reasons=summ.get('reasons'), status=summ.get('status'),
                               parts=summ.get('parts'))
        # ---------------------------------------------------------------- inputs to the issue maker
        pipeline_out = os.path.join(W, 'pipeline_out')
        shutil.copytree(os.path.join(PO, 'out'), pipeline_out)
        source_dir = os.path.join(W, 'source')
        if src_dir:
            shutil.copytree(src_dir, source_dir)
        else:
            os.makedirs(source_dir)
        T = os.path.join(W, 'pkg')
        step_rel = job['step'].replace('\\', '/').lstrip('/')
        step_path = os.path.join(T, step_rel)
        d = C.download(job['urls']['step'], step_path, sha256=job.get('step_sha256'), nbytes=job.get('bytes'), log=log)
        res['delivered'] = dict(relpath=step_rel, bytes=d['bytes'], sha256=d['sha256'])

        def fetch(key, dest, sha256=None, nbytes=None):
            return C.download(job['urls'][key], dest, sha256=sha256, nbytes=nbytes, log=log)
        sys.path.insert(0, '/pmp/issues')
        import importlib.util
        spec = importlib.util.spec_from_file_location('issues_stage', '/pmp/issues/stage.py')
        stage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stage)
        maker_out = os.path.join(W, 'maker_out')
        os.makedirs(os.path.join(W, 'maker'))
        mf = job['model_folder']
        ctx = dict(stage='issues', work=os.path.join(W, 'maker'), out=maker_out, model_dir=f'/vol/{ID}', cls=job['cls'], J=J,
                   deadline=time.time() + 3600, log=log, fetch=fetch, step_path=step_path, ifc_path=ifc,
                   pipeline_out=pipeline_out, source_dir=source_dir, pipeline=summ, model_folder=mf, issues_name=mf,
                   code_dir=f"/pmp/code/{job['code_version']}")
        t0 = time.time()
        r = stage.run(job, ctx)
        res['steps']['make_issues'] = dict(ok=r.get('ok'), seconds=round(time.time() - t0, 1), error=r.get('error'),
                                           detail_files=r.get('detail_files'), detail_missing=r.get('detail_missing'),
                                           stdout=(r.get('maker_stdout') or '')[-3000:])
        if not r.get('ok'):
            res['error'] = f"make_issues failed: {r.get('error')}"
            return res
        iss = json.load(open(os.path.join(maker_out, 'schedules', 'issues.json')))
        res['issues_counts'] = iss['counts']
        res['reconciliation'] = iss.get('reconciliation')
        res['script_shortfall'] = iss.get('script_shortfall')
        res['not_drawn'] = iss.get('not_drawn')
        res['checks_made'] = iss.get('checks')
        res['categories'] = iss.get('categories')
        # ---------------------------------------------------------------- package-shaped tree, as published
        kit = f"/pmp/code/{job['code_version']}/kit"
        S = os.path.join(T, 'scripts')
        M = os.path.join(S, mf)
        os.makedirs(os.path.join(M, 'schedules'))
        shutil.copy(os.path.join(kit, 'steelbuild.py'), S)
        shutil.copy('/pmp/issues/issues_lib.py', S)
        shutil.copy(os.path.join(kit, 'build_model.py'), M)
        shutil.copy('/pmp/issues/build_issues_model.py', M)
        for f in SCHEDULE_FILES:
            if os.path.exists(os.path.join(pipeline_out, f)):
                shutil.copy(os.path.join(pipeline_out, f), os.path.join(M, 'schedules'))
        for f in ('issues.json', 'missing_parts.json'):
            shutil.copy(os.path.join(maker_out, 'schedules', f), os.path.join(M, 'schedules'))
        os.makedirs(os.path.join(M, 'issues'))
        shutil.copy(os.path.join(maker_out, 'issues', 'WHERE_TO_LOOK.md'), os.path.join(M, 'issues'))
        clean = os.path.join(W, 'clean')                    # a pristine copy of the tree for the later runs
        shutil.copytree(T, clean)

        def fresh(name):
            dst = os.path.join(W, name)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(clean, dst)
            return dst, os.path.join(dst, 'scripts', mf)

        def outputs(m):
            d_ = os.path.join(m, 'issues')
            return {f: dict(bytes=os.path.getsize(os.path.join(d_, f)), sha256=sha(os.path.join(d_, f)))
                    for f in sorted(os.listdir(d_)) if f.lower().endswith('.step')}
        # 1. THE run (default mode), with the read-back check
        rc, out = run([PY, 'build_issues_model.py', '--jobs', str(J), '--verify'], M, 'default')
        o1 = outputs(M)
        res['outputs_default'] = o1
        hl, mo = f'{mf}_ISSUES_highlighted.step', f'{mf}_MISSING_parts_only.step'
        n_missing = len(json.load(open(os.path.join(M, 'schedules', 'missing_parts.json')))['parts'])
        res['checks']['default_rc0'] = rc == 0
        res['checks']['highlighted_written'] = hl in o1
        res['checks']['missing_only_iff_missing'] = (mo in o1) == bool(n_missing)
        mrb = re.search(r'^read back: (\{.*\})$', out, re.M)
        res['readback_default'] = json.loads(mrb.group(1)) if mrb else None
        res['checks']['default_readback_counts_equal_issues_json'] = bool(mrb) and all(
            res['readback_default']['counts'].get(c, 0) == v for c, v in iss['counts']['rebuild'].items()) and \
            sum(res['readback_default']['counts'].values()) == sum(iss['counts']['rebuild'].values())
        # 2. byte-identical regeneration: a fresh copy of the tree, --jobs 1
        T2, M2 = fresh('det')
        rc2, _ = run([PY, 'build_issues_model.py', '--jobs', '1'], M2, 'determinism')
        o2 = outputs(M2)
        res['outputs_determinism'] = o2
        res['checks']['regenerated_byte_identical'] = rc2 == 0 and o2 == o1
        diffs = {}
        for f in o1:
            if f in o2 and o1[f] != o2[f]:
                a_ = open(os.path.join(M, 'issues', f), 'rb').read().splitlines()
                b_ = open(os.path.join(M2, 'issues', f), 'rb').read().splitlines()
                dl = [(i, x[:200].decode('latin-1'), y[:200].decode('latin-1')) for i, (x, y) in enumerate(zip(a_, b_)) if x != y]
                diffs[f] = dict(lines=(len(a_), len(b_)), n_diff=len(dl), first=dl[:6])
        res['determinism_diffs'] = diffs
        # 3. --from-delivered (the delivered STEP at its package path), text check + read-back
        T3, M3 = fresh('dlv')
        rc3, out3 = run([PY, 'build_issues_model.py', '--from-delivered', '--verify'], M3, 'from_delivered')
        o3 = outputs(M3)
        res['outputs_from_delivered'] = o3
        mt = re.search(r'^text check: (\{.*\})$', out3, re.M)
        mr = re.search(r'^read back: (\{.*\})$', out3, re.M)
        res['text_check_delivered'] = json.loads(mt.group(1)) if mt else None
        res['readback_delivered'] = json.loads(mr.group(1)) if mr else None
        res['checks']['from_delivered_rc0'] = rc3 == 0
        res['checks']['from_delivered_geometry_unchanged'] = bool(mt) and res['text_check_delivered']['n_bad_edits'] == 0 \
            and res['text_check_delivered']['missing'] == 0
        res['checks']['from_delivered_counts_equal_issues_json'] = bool(mt) and \
            res['text_check_delivered']['counts'] == {c: iss['counts']['delivered'].get(c, 0) for c in iss['counts']['delivered']}
        res['checks']['delivered_step_unchanged'] = sha(os.path.join(T3, step_rel)) == res['delivered']['sha256']
        res['checks']['missing_only_same_in_both_modes'] = o3.get(mo) == o1.get(mo)
        # the same --from-delivered run again: byte-identical
        T4, M4 = fresh('dlv2')
        rc4, _ = run([PY, 'build_issues_model.py', '--from-delivered'], M4, 'from_delivered_again')
        res['checks']['from_delivered_byte_identical'] = rc4 == 0 and outputs(M4) == o3
        # 4. --list
        rc5, out5 = run([PY, 'build_issues_model.py', '--list'], M2, 'list', timeout=600)
        ml = re.search(r'^\s*rebuild\s*:\s*(.*)$', out5, re.M)
        listed = {c: int(n) for c, n in re.findall(r'\b(GREY|RED|ORANGE|YELLOW|PURPLE)\s+(\d+)', ml.group(1))} if ml else {}
        res['checks']['list_counts_equal_issues_json'] = rc5 == 0 and listed == iss['counts']['rebuild']
        res['ok'] = all(v is True for v in res['checks'].values())
        res['failed_checks'] = [k for k, v in res['checks'].items() if v is not True]
        # ---------------------------------------------------------------- publish the results to the volume
        P = os.path.join(W, 'publish')
        os.makedirs(P)
        shutil.copytree(os.path.join(M, 'schedules'), os.path.join(P, 'schedules'),
                        ignore=lambda d_, fs: [f for f in fs if f not in ('issues.json', 'missing_parts.json')])
        shutil.copytree(os.path.join(M, 'issues'), os.path.join(P, 'issues'))
        for f in o3:
            if f not in o1:
                shutil.copy(os.path.join(M3, 'issues', f), os.path.join(P, 'issues', f))
        os.makedirs(os.path.join(P, 'runs'))
        for f in os.listdir(W):
            if f.endswith('.out') or f == 'unit.log':
                shutil.copy(os.path.join(W, f), os.path.join(P, 'runs', f))
    except Exception as e:
        res['ok'] = False
        res['error'] = f'{type(e).__name__}: {e}'
        res['traceback'] = traceback.format_exc()[-4000:]
        P = os.path.join(W, 'publish')
        os.makedirs(os.path.join(P, 'runs'), exist_ok=True)
        if os.path.exists(logp):
            shutil.copy(logp, os.path.join(P, 'runs', 'unit.log'))
    res['seconds'] = round(time.time() - T0, 1)
    C.write_json(os.path.join(P, 'result.json'), res)
    dst = f'{UD}/unit'
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(P, dst)
    vol.commit()
    return res


@app.local_entrypoint()
def main(tags: str = 'n1_db1_small,n5_sds2', no_pipeline: bool = False, pull: bool = True):
    want = [t.strip() for t in tags.split(',') if t.strip()]
    new5 = {r['tag']: r for r in json.load(open(NEW5))}
    forbidden = json.load(open(FORBIDDEN)) if FORBIDDEN.exists() else []
    forbidden = forbidden if isinstance(forbidden, list) else list(forbidden)
    rows = {}
    for line in open(SIGNED):
        j = json.loads(line)
        if j.get('tag') in want:
            if j.get('tag') not in new5 or new5[j['tag']]['model_id'] != j['model_id']:
                raise SystemExit(f"{j.get('tag')}: not one of the 5 new samples - refused")
            rows[j['tag']] = j
    missing = [t for t in want if t not in rows]
    if missing:
        raise SystemExit(f'not in {SIGNED.name}: {missing}')
    out = {}
    for tag, r in zip(rows, unit.map([rows[t] for t in rows], kwargs={'forbidden': forbidden, 'run_pipeline': not no_pipeline},
                                     return_exceptions=True)):
        out[tag] = r if isinstance(r, dict) else {'ok': False, 'error': repr(r)[:2000]}
    resd = HERE / 'results'
    resd.mkdir(exist_ok=True)
    for tag, r in out.items():
        td = resd / tag
        td.mkdir(exist_ok=True)
        (td / 'result.json').write_text(json.dumps(r, indent=1, default=str))
        print(f"== {tag}: ok={r.get('ok')} blocked={r.get('blocked')} error={r.get('error')} failed={r.get('failed_checks')}")
        print('   counts', json.dumps(r.get('issues_counts')))
        if pull and r.get('model_id') and not r.get('blocked'):
            import subprocess
            subprocess.run([str(ROOT / '.venv' / 'bin' / 'modal'), 'volume', 'get', '--force', 'pmp-out',
                            f"/_unit/issues/{r['model_id']}/unit", str(td)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
