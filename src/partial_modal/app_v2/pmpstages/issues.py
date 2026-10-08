"""issues stage (+ package): for ONE model, in the pipeline image

  1. make_issues (issues plug-in): schedules/issues.json, schedules/missing_parts.json, issues/WHERE_TO_LOOK.md from
     the partial record, the conversion detail, the source stage's side tables, the source IFC and our verification;
  2. package.assemble: the scripts/ tree exactly as published (shared files + scripts/<model_folder>/...), inside a
     package-shaped root that also holds the delivered STEP at its package path (model/step/...), so the shipped
     scripts can be run exactly as a user runs them from the package;
  3. RUN THE SHIPPED SCRIPT from that tree: `python build_issues_model.py` (cwd = scripts/<model_folder>) writes
     issues/<model>_ISSUES_highlighted.step (+ _MISSING_parts_only.step): these are the files that get published;
  4. its own end-to-end checks (verification/issues_e2e.json): a second default run in a copy of the tree (different
     --jobs when the script has the option) must give byte-identical DATA sections; `--from-delivered` on the delivered
     STEP must run clean in another copy; `--list` counts must agree with what the maker reports; any reference copy the
     maker wrote (ref/) must be reproduced byte for byte;
  5. scripts_manifest rows (sha256 per file), layout check, deterministic bundle -> /<id>/bundle/<run>/<id>.tar.gz.
A model whose checks fail gets no bundle (ok=False, reasons listed): a package never receives files its scripts
cannot regenerate.
"""
import json, os, re, shutil, subprocess, sys, time, traceback

from . import common as C
from . import package as K
from . import plugins
from .source import make_fetch

PY = sys.executable
COLOURS = ('GREY', 'RED', 'ORANGE', 'YELLOW', 'PURPLE')


def _run(cmd, cwd, timeout, logf):
    t0 = time.time()
    with open(logf, 'a') as lf:
        lf.write(f'\n$ (cwd {os.path.basename(cwd)}) {" ".join(cmd[1:])}\n')
        lf.flush()
        try:
            p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               timeout=max(30, timeout), text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            out, rc = p.stdout, p.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = (e.stdout or '') if isinstance(e.stdout, str) else '', 124
        lf.write(out[-20000:])
        lf.write(f'\n[rc {rc}, {time.time() - t0:.1f}s]\n')
    return rc, out, round(time.time() - t0, 1)


def _outputs(model_dir):
    d = os.path.join(model_dir, 'issues')
    return sorted(f for f in os.listdir(d) if f.lower().endswith(('.step', '.stp'))) if os.path.isdir(d) else []


def _parse_counts(text):
    """colour counts printed by `build_issues_model.py --list`: its 'rebuild  : GREY n, RED n, ...' line; else JSON (a
    dict, or a dict under 'counts'), else 'COLOUR ... <n>' lines; {} when nothing recognisable"""
    m = re.search(r'^\s*rebuild\s*:\s*(.*)$', text, re.M)
    if m:
        got = {c.upper(): int(n) for c, n in re.findall(r'\b(GREY|RED|ORANGE|YELLOW|PURPLE)\s+(\d+)', m.group(1))}
        if got:
            return got
    for chunk in (text, text[text.find('{'):text.rfind('}') + 1] if '{' in text else ''):
        try:
            d = json.loads(chunk)
            d = d.get('counts', d) if isinstance(d, dict) else None
            if isinstance(d, dict) and any(k.upper() in COLOURS for k in d):
                return {k.upper(): int(v) for k, v in d.items() if k.upper() in COLOURS and isinstance(v, (int, float))}
        except Exception:
            pass
    out = {}
    for line in text.splitlines():
        m = re.match(r'\s*(GREY|GRAY|RED|ORANGE|YELLOW|PURPLE)\b\D*?(\d+)', line, re.I)
        if m:
            out[m.group(1).upper().replace('GRAY', 'GREY')] = int(m.group(2))
    return out


def _copy_tree_for_run(T, dst, step_rel, link=True):
    """a fresh package-shaped root for a check run: scripts/ (without the issues STEP outputs) + the delivered STEP
    (hard link, or a copy when the run must not be able to touch the original)"""
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(T, 'scripts'), os.path.join(dst, 'scripts'),
                    ignore=lambda d, fs: [f for f in fs if os.path.basename(d) == 'issues' and f.lower().endswith(('.step', '.stp'))])
    os.makedirs(os.path.dirname(os.path.join(dst, step_rel)), exist_ok=True)
    (os.link if link else shutil.copyfile)(os.path.join(T, step_rel), os.path.join(dst, step_rel))


def run(job, cls, deadline, run_name, workroot='/tmp/pmp', keep_tree=True):
    t0 = time.time()
    cpu = C.CpuMeter()
    mem = C.MemSampler()
    ID, STEM, mf = job['id'], job['id'][:16], job['model_folder']
    J = C.RES[cls]['J']
    MD = os.path.join(C.VOL, ID)
    JD = os.path.join(workroot, STEM + '.issues')
    shutil.rmtree(JD, ignore_errors=True)
    work, maker_out, T = (os.path.join(JD, x) for x in ('work', 'maker_out', 'pkg'))
    for d in (work, maker_out, T):
        os.makedirs(d)
    LOGF = os.path.join(JD, 'log', 'issues_runs.log')
    log = C.StageLog(os.path.join(JD, 'log', 'issues.log'), prefix=f'[{STEM} issues] ')
    rec = {'ok': False, 'stage': 'issues', 'cls': cls, 'error': None, 'reasons': []}
    e2e = {'model_id': ID, 'model_folder': mf, 'runs': {}, 'checks': {}}
    log(f'start issues+package {ID} cls {cls} run {run_name}')
    try:
        summ = C.read_json(os.path.join(MD, 'pipeline', 'summary.json'))
        if not summ or not os.path.isdir(os.path.join(MD, 'pipeline', 'out')):
            raise RuntimeError('no pipeline output on the volume for this model')
        if (summ.get('steps') or {}).get('download') != 0:
            raise RuntimeError(f'pipeline did not run (download rc {(summ.get("steps") or {}).get("download")})')
        e2e_inputs = C.read_json(os.path.join(MD, 'pipeline', 'e2e_inputs.json'), {})
        pipeline_out = os.path.join(work, 'pipeline_out')
        shutil.copytree(os.path.join(MD, 'pipeline', 'out'), pipeline_out)
        source_dir = os.path.join(work, 'source')
        if os.path.isdir(os.path.join(MD, 'source')):
            shutil.copytree(os.path.join(MD, 'source'), source_dir)
        else:
            os.makedirs(source_dir)
        fetch = make_fetch(job, log)
        step_rel = job['step'].replace('\\', '/').lstrip('/')
        step_path = os.path.join(T, step_rel)
        fetch('step', step_path, sha256=job.get('step_sha256'), nbytes=job.get('bytes'))
        _ov = os.path.join(MD, 'complete_sds2_ifc', 'sanitized_source.ifc')   # completion: IFC with a dangling ref repaired
        if job['source_kind'] == 'package_ifc' and os.path.isfile(_ov):
            ifc_path = os.path.join(work, 'source.ifc')
            shutil.copy(_ov, ifc_path)
            log('source IFC: the sanitized copy ' + _ov)
        elif job['source_kind'] == 'package_ifc':
            ifc_path = os.path.join(work, 'source.ifc')
            fetch('ifc', ifc_path, sha256=job.get('source_ifc_sha256'))
        else:
            ifc_path = os.path.join(source_dir, os.path.basename(job['ifc']))
            if not os.path.isfile(ifc_path):
                raise RuntimeError(f'source IFC {job["ifc"]} not in /<id>/source/')
        # 1. issue maker
        ctx = dict(stage='issues', work=os.path.join(work, 'maker'), out=maker_out, model_dir=MD, cls=cls, J=J, deadline=deadline,
                   log=log, fetch=fetch, code_dir=os.path.join(C.CODE_ROOT, job['code_version']), step_path=step_path,
                   ifc_path=ifc_path, pipeline_out=pipeline_out, source_dir=source_dir, pipeline=summ, model_folder=mf,
                   issues_name=mf)
        os.makedirs(ctx['work'])
        mod = plugins.load('issues')
        r = mod.run(job, ctx) or {}
        if not isinstance(r, dict):
            raise TypeError(f'issues.run returned {type(r).__name__}, expected dict')
        rec['maker'] = {k: v for k, v in r.items() if k not in ('ok', 'error')}
        if not r.get('ok'):
            raise RuntimeError(f'make_issues failed: {r.get("error")}')
        maker_counts = r.get('counts')
        missing_n = K.count_missing(os.path.join(maker_out, 'schedules', 'missing_parts.json'))
        # 2. assemble the tree
        asm = K.assemble(job, T, pipeline_out, source_dir, maker_out, summ, e2e_inputs, log, issues_counts=maker_counts)
        M = asm['model_dir']
        e2e['shipped_build_inputs_equal_e2e_tested'] = asm['e2e_inputs_check']
        helptxt = _run([PY, 'build_issues_model.py', '--help'], M, 120, LOGF)[1]
        has_jobs = '--jobs' in helptxt
        left = lambda: deadline - time.time() - 120
        # 3. THE run whose outputs are published: default mode, from the tree, as a user runs it
        cmd = [PY, 'build_issues_model.py'] + (['--jobs', str(J)] if has_jobs else [])
        rc, out, dt = _run(cmd, M, left(), LOGF)
        outs = _outputs(M)
        e2e['runs']['default'] = {'cmd': ' '.join(cmd[1:]), 'rc': rc, 'seconds': dt, 'outputs': {
            f: {'bytes': os.path.getsize(os.path.join(M, 'issues', f)), 'sha256': C.file_sha256(os.path.join(M, 'issues', f)),
                'data_sha256': C.step_data_sha256(os.path.join(M, 'issues', f))} for f in outs}, 'tail': out[-1500:]}
        log(f'build_issues_model.py rc={rc} {dt}s outputs {outs}')
        hl, mo = f'{mf}_ISSUES_highlighted.step', f'{mf}_MISSING_parts_only.step'
        e2e['checks']['default_rc0'] = rc == 0
        e2e['checks']['highlighted_written'] = hl in outs
        e2e['checks']['missing_only_written_iff_missing'] = (mo in outs) == bool(missing_n) if missing_n is not None else None
        e2e['missing_parts'] = missing_n
        # 4a. determinism: the same run again in a copy (other --jobs when available)
        T2 = os.path.join(JD, 'det')
        _copy_tree_for_run(T, T2, step_rel)
        M2 = os.path.join(T2, 'scripts', mf)
        cmd2 = [PY, 'build_issues_model.py'] + (['--jobs', str(1 if J != 1 else 2)] if has_jobs else [])
        rc2, out2, dt2 = _run(cmd2, M2, left(), LOGF)
        outs2 = _outputs(M2)
        same = {f: (f in outs2 and C.step_data_sha256(os.path.join(M2, 'issues', f)) == e2e['runs']['default']['outputs'][f]['data_sha256'])
                for f in outs}
        e2e['runs']['determinism'] = {'cmd': ' '.join(cmd2[1:]), 'rc': rc2, 'seconds': dt2, 'outputs': outs2, 'data_identical': same}
        e2e['checks']['deterministic'] = rc2 == 0 and outs2 == outs and all(same.values())
        # 4b. --from-delivered on the delivered STEP at its package path
        T3 = os.path.join(JD, 'dlv')
        _copy_tree_for_run(T, T3, step_rel, link=False)
        M3 = os.path.join(T3, 'scripts', mf)
        rel_step = os.path.relpath(os.path.join(T3, step_rel), M3)
        cmd3 = [PY, 'build_issues_model.py', '--from-delivered', rel_step]
        rc3, out3, dt3 = _run(cmd3, M3, left(), LOGF)
        outs3 = _outputs(M3)
        e2e['runs']['from_delivered'] = {'cmd': ' '.join(cmd3[1:]), 'rc': rc3, 'seconds': dt3, 'outputs': {
            f: {'bytes': os.path.getsize(os.path.join(M3, 'issues', f)), 'data_sha256': C.step_data_sha256(os.path.join(M3, 'issues', f))}
            for f in outs3}, 'tail': out3[-1500:]}
        e2e['checks']['from_delivered_rc0'] = rc3 == 0 and bool(outs3)
        e2e['checks']['delivered_step_unchanged'] = C.file_sha256(os.path.join(T3, step_rel)) == C.file_sha256(step_path)
        # 4c. --list counts vs the maker's counts
        rc4, out4, _ = _run([PY, 'build_issues_model.py', '--list'], M2, min(600, left()), LOGF)
        listed = _parse_counts(out4)
        e2e['runs']['list'] = {'rc': rc4, 'counts': listed, 'tail': out4[-1500:]}
        if maker_counts and listed:
            mc = {k.upper(): int(v) for k, v in maker_counts.items() if k.upper() in COLOURS}
            e2e['checks']['list_counts_equal_maker'] = all(listed.get(k, 0) == mc.get(k, 0) for k in COLOURS)
        else:
            e2e['checks']['list_counts_equal_maker'] = None
            e2e['list_note'] = 'not compared: ' + ('the maker reported no counts' if not maker_counts else '--list printed no recognisable counts')
        # 4d. reference copies from the maker (ref/): reproduced byte for byte (DATA section)
        refd = os.path.join(maker_out, 'ref')
        refs = {}
        if os.path.isdir(refd):
            prod = {**{f: os.path.join(M, 'issues', f) for f in outs}, **{'delivered:' + f: os.path.join(M3, 'issues', f) for f in outs3}}
            for f in sorted(os.listdir(refd)):
                want = C.step_data_sha256(os.path.join(refd, f))
                hit = [k for k, p in prod.items() if os.path.basename(k.split(':')[-1]) == f and C.step_data_sha256(p) == want]
                refs[f] = hit[0] if hit else None
            e2e['checks']['maker_references_reproduced'] = all(refs.values())
        e2e['maker_references'] = refs
        failed = [k for k, v in e2e['checks'].items() if v is False]
        e2e['ok'] = not failed
        e2e['failed_checks'] = failed
        rec['reasons'] = failed
        C.write_json(os.path.join(M, 'verification', 'issues_e2e.json'), e2e)
        if failed:
            raise RuntimeError(f'issues checks failed: {failed}')
        # 5. manifest + layout + bundle (byte-code caches are never shipped)
        S = os.path.join(T, 'scripts')
        for dp, dn, _ in os.walk(S):
            for x in [x for x in dn if x == '__pycache__']:
                shutil.rmtree(os.path.join(dp, x))
        # the layout the published package will hold (exactly one highlighted STEP; MISSING only with missing parts)
        want = sorted([hl] + ([mo] if missing_n else []))
        if (outs != want) if missing_n is not None else (hl not in outs or not set(outs) <= {hl, mo}):
            rec['reasons'].append('issues_outputs')
            raise RuntimeError(f'build_issues_model.py wrote {outs}, expected {want}')
        bdest = os.path.join(JD, 'bundle', f'{ID}.tar.gz')
        b = K.make_bundle(job, T, asm['prov'], asm['code_versions'], run_name, bdest)   # bundle_lib verifies it
        rows = b.pop('rows')
        log(f'bundle {b["bytes"]} B sha256 {b["sha256"][:12]} ({b["n_files"]} files) warnings {b.get("warnings")}')
        # publish to the volume: bundle + its rows + facts, and the tree for inspection
        BD = os.path.join(JD, 'bundle_pub')
        os.makedirs(BD)
        shutil.copy(bdest, os.path.join(BD, f'{ID}.tar.gz'))
        with open(os.path.join(BD, 'scripts_manifest_rows.jsonl'), 'w') as f:
            for r_ in rows:
                f.write(json.dumps(r_, sort_keys=True) + '\n')
        facts = dict(run=run_name, model_id=ID, pid=job['pid'], model_folder=mf, sha256=b['sha256'], bytes=b['bytes'],
                     md5_hex=b['md5_hex'], n_files=b['n_files'], header=b['header'], warnings=b.get('warnings'),
                     verdict=dict(perfect=summ.get('perfect'), reasons=summ.get('reasons')), issues_counts=maker_counts,
                     missing_parts=missing_n, issues_e2e_ok=e2e['ok'])
        C.write_json(os.path.join(BD, 'bundle_facts.json'), facts)
        C.publish(BD, os.path.join(MD, 'bundle', run_name))
        if keep_tree:
            C.publish(S, os.path.join(MD, 'scripts_tree'))
        rec.update(ok=True, bundle=dict(path=os.path.join(MD, 'bundle', run_name, f'{ID}.tar.gz'), sha256=b['sha256'],
                                        bytes=b['bytes'], md5=b['md5_hex'], n_files=b['n_files'], warnings=b.get('warnings')),
                   counts=maker_counts, missing_parts=missing_n, list_counts=listed,
                   outputs=e2e['runs']['default']['outputs'], code_versions=asm['code_versions'])
    except Exception as e:
        rec['ok'] = False
        rec['error'] = f'{type(e).__name__}: {e}'
        log('EXCEPTION ' + traceback.format_exc())
        shutil.rmtree(os.path.join(MD, 'bundle', run_name), ignore_errors=True)   # never leave a stale bundle looking current
    rec['issues_e2e'] = {k: e2e.get(k) for k in ('ok', 'failed_checks', 'checks')}
    rec['seconds'] = round(time.time() - t0, 1)
    rec['cpu_seconds'] = cpu.done()
    rec['peak_gib'], rec['peak_how'] = mem.done()
    rec['container'] = C.container_info(cls)
    log(f'done ok={rec["ok"]} error={rec["error"]} {rec["seconds"]}s')
    L = os.path.join(JD, 'logs_pub')
    os.makedirs(L)
    for f in ('issues.log', 'issues_runs.log'):
        if os.path.exists(os.path.join(JD, 'log', f)):
            shutil.copy(os.path.join(JD, 'log', f), L)
    C.write_json(os.path.join(L, 'issues_e2e.json'), e2e)
    if os.listdir(maker_out):
        shutil.copytree(maker_out, os.path.join(L, 'maker_out'))
    C.publish(L, os.path.join(MD, 'logs', 'issues'))
    shutil.rmtree(JD, ignore_errors=True)
    return rec
