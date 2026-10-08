"""pipeline stage: the pmx job (code/reference/job.py = fleet benchkit/job.py) for ONE model on a Modal container.

  inputs (delivered STEP from its pre-signed URL; source IFC from its pre-signed URL - the package IFC - or from the
  volume where the source stage put it) -> extract+exact -> props -> recover -> views -> verify -> reference_defects
  -> verify_levels -> tekla_checks -> e2e  ->  outputs to the volume:
     /<id>/pipeline/out/            job.py's flat out folder (schedules, verification, logs, pmx_summary.json ...)
     /<id>/pipeline/summary.json    = out/pmx_summary.json (job.py's summary: verdict + run facts)
     /<id>/pipeline/e2e_inputs.json sha256 of every file the e2e step ran (scripts/steelbuild.py, build_model.py,
                                    schedules/*): the package stage ships exactly these bytes
     /<id>/source/provenance.json   (package-IFC models: where the source IFC is and its checked sha256)

Same steps, commands, arguments, order, per-step timeouts (by size class), failure handling (a failed or timed-out
step is recorded with its rc and the next steps still run) and verdict as job.py. Differences, all outside the
pipeline's own computation:
  * inputs come from pre-signed GET URLs / the volume instead of boto3 (no AWS credentials on Modal);
  * no heartbeat / S3 upload / done marker: outputs are published to the Modal Volume;
  * PY = this image's python (pinned requirements = the fleet's freeze); code dir = /pmp/code/<variant>, whose files
    are checked against the variant's MD5SUMS before the run (a mismatch stops the stage: wrong code never runs);
  * a step is not started past the container's deadline (Modal timeout - STOP_MARGIN): it is recorded rc 124 like
    a job.py timeout, so the summary is always written;
  * peak_rss_gb is measured in the container (job.py takes it from the worker).
pmx_summary.json carries exactly job.py's keys; Modal-side facts go to the stage result / run index.
"""
import hashlib, json, os, shutil, subprocess, sys, time

from . import common as C

PY = sys.executable
STEPS = ('extract+exact', 'props', 'recover', 'views', 'verify', 'reference_defects', 'verify_levels', 'tekla_checks',
         'e2e')
SCHEDULE_FILES = ('parts.csv', 'profiles.csv', 'profile_outlines.json', 'solids.csv', 'cuts.csv', 'cut_boundaries.json',
                  'openings.csv', 'paths.json', 'exact_geometry.jsonl', 'assemblies.csv')
MEMORY_KILL_RCS = (-9, 137)        # SIGKILL not sent by us (our timeout kill is recorded 124): the OOM killer


# ------------------------------------------------------------------------------------------------ verdict (verbatim)
def make_verdict(O):
    def jload(name):
        try:
            return json.load(open(os.path.join(O, name)))
        except Exception:
            return None

    def verdict(rcs):
        """per-model summary + 'perfect' flag: every step ran clean, every part built and matching both references, the
        combined model and every assembly / mark level ok, and the packaged script's end-to-end runs (whole model,
        determinism, assemblies, marks) all ok"""
        vs, lv, e2, rd, rs = (jload('verification_summary.json'), jload('levels_summary.json'), jload('e2e_summary.json'),
                              jload('reference_defects_summary.json'), jload('recover_summary.json'))
        reasons = [f'step_{k}_rc{v}' for k, v in rcs.items() if v != 0]
        s = {'steps': rcs}
        if vs:
            st = vs.get('status', {})
            s.update(parts=vs.get('parts'), status=st, status_by_geometry=vs.get('status_by_geometry'),
                     source_check=vs.get('source_check'), delivered_check=vs.get('delivered_check'),
                     not_built=vs.get('delivered_parts_not_built'), delivered_parts=vs.get('delivered_parts'),
                     source_coverage={k: v for k, v in (vs.get('source_coverage') or {}).items() if not isinstance(v, (dict, list))})
            if not vs.get('parts'):
                reasons.append('no_parts')
            if st.get('match', 0) != vs.get('parts'):
                reasons.append('parts_not_all_match')
            if vs.get('delivered_parts_not_built'):
                reasons.append('delivered_parts_not_built')
        else:
            reasons.append('no_verification_summary')
        if lv:
            m = lv.get('model', {})
            s['levels'] = {'model': {k: m.get(k) for k in ('geometry_ok', 'parts_and_combined_geometry_ok', 'assemblies_ok',
                                                            'assembly_marks_ok', 'piece_marks_ok', 'source_consistent',
                                                            'delivered_consistent')},
                           'assemblies': lv.get('assemblies'), 'assembly_marks': lv.get('assembly_marks'),
                           'piece_marks': lv.get('piece_marks')}
            if not m.get('geometry_ok'):
                reasons.append('levels_not_ok')
        else:
            reasons.append('no_levels_summary')
        if e2:
            s['e2e'] = {k: e2.get(k) for k in ('model', 'determinism', 'assembly', 'piece', 'model_parts_in_step',
                                                 'model_parts_ok', 'model_parts_failing', 'model_failing_by_reason')}
            for k in ('model', 'determinism', 'assembly', 'piece'):
                r = e2.get(k) or {}
                if r.get('ok') != r.get('runs'):
                    reasons.append(f'e2e_{k}')
            if not (e2.get('model') or {}).get('runs'):
                reasons.append('e2e_model_not_run')
        else:
            reasons.append('no_e2e_summary')
        if rd:
            s['reference_defects'] = rd.get('verdict')
        if rs:
            s['recover'] = rs
        s['perfect'] = not reasons
        s['reasons'] = reasons
        return s

    return verdict


def _sha_tree(root):
    out = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = C.file_sha256(p)
    return dict(sorted(out.items()))


# ------------------------------------------------------------------------------------------------------- the stage
def run(job, ifc_spec, cls, deadline, workroot='/tmp/pmp', publish_rel='pipeline'):
    """job: normalised job (common.normalise_job). ifc_spec: where the source IFC comes from:
         {'mode': 'package', 'url_key': 'ifc'}                        the package IFC, pre-signed URL in job['urls']
         {'mode': 'volume', 'path': '/vol/<id>/source/<f>', 'sha256'}  written by the src_db1 / src_sds2 stage
       cls: the size class this container was started with (resources + step timeouts). deadline: epoch seconds.
       Returns the stage result (small dict); the outputs are on the volume (caller commits)."""
    t_start = time.time()
    cpu = C.CpuMeter()
    res = C.RES[cls]
    ID, GEN, J = job['id'], job['gen'], res['J']
    CODE = os.path.join(C.CODE_ROOT, job['code_version'])
    STEM = ID[:16]
    JD = os.path.join(workroot, STEM + '.pipeline')
    shutil.rmtree(JD, ignore_errors=True)
    W = os.path.join(JD, 'w')
    O = os.path.join(W, 'out', STEM)
    SRC = os.path.join(W, 'src')
    LOG = os.path.join(JD, 'job.log')
    TMO = res['step_timeout']
    os.makedirs(O, exist_ok=True)
    os.makedirs(SRC, exist_ok=True)
    mem = C.MemSampler()
    MD = os.path.join(C.VOL, ID)

    def log(msg):
        with open(LOG, 'a') as f:
            f.write(time.strftime('%H:%M:%S ') + msg + '\n')
        print(f'[{STEM} pipeline] {msg}', flush=True)

    def run_step(name, logname, cmd, cwd=None, timeout=TMO):
        t0 = time.time()
        left = deadline - t0
        with open(os.path.join(O, logname), 'a') as lf:
            if left < 30:
                lf.write(f'\nNOT STARTED: container deadline reached ({left:.0f}s left)\nTIMEOUT after 0s\n')
                rc = 124
            else:
                timeout = min(timeout, left)
                try:
                    p = subprocess.Popen(cmd, cwd=cwd or CODE, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                         start_new_session=True, env=dict(os.environ, EXACT_JOBS=str(J)))
                    try:
                        rc = p.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        os.killpg(p.pid, 9)
                        p.wait()
                        rc = 124
                        lf.write(f'\nTIMEOUT after {timeout:.0f}s\n')
                except Exception as e:
                    lf.write(f'\nLAUNCH ERROR {e!r}\n')
                    rc = 127
        dt = time.time() - t0
        with open(os.path.join(O, 'step_times.tsv'), 'a') as f:
            f.write(f'{name}\t{rc}\t{dt:.3f}\n')
        log(f'{name} rc={rc} {dt:.0f}s')
        return rc

    with open(os.path.join(O, 'step_times.tsv'), 'w') as f:
        f.write('step\texit_code\tseconds\n')
    log(f'start {ID} gen {GEN} cls {cls} J {J} code {CODE}')
    md5 = C.check_md5sums(CODE)
    log(f'code {job["code_version"]} MD5SUMS: {md5["checked"]} files, bad {md5["bad"]}')
    step_local = os.path.join(SRC, STEM + '.step')
    ifc_name = job.get('ifc') or (ID + '.ifc')
    ifc_local = os.path.join(SRC, STEM + ('.ifczip' if ifc_name.lower().endswith('.ifczip') else '.ifc'))
    rcs = {}
    dl = {}
    source_rec = None
    try:
        if not md5['ok']:
            raise RuntimeError(f'code variant {job["code_version"]} does not match its MD5SUMS: {md5["bad"][:5]}')
        dl['step'] = C.download(job['urls']['step'], step_local, sha256=job.get('step_sha256'), nbytes=job.get('bytes'),
                                log=log)
        if ifc_spec['mode'] == 'package':
            exp = job.get('source_ifc_sha256')
            dl['ifc'] = C.download(job['urls'][ifc_spec.get('url_key', 'ifc')], ifc_local, sha256=exp, log=log)
            pkg = job.get('converted_from_package') or f'cad-disk-extract/dataset/packages/3d_partial/{job["pid"]}'
            source_rec = {
                'source_kind': 'package_ifc', 'model_id': ID, 'source_ifc': ifc_name,
                'source_ifc_location': f'{pkg.rstrip("/")}/{ifc_name}',
                'source_ifc_in_package': ('the add-on package' if job.get('converted_from_package') else 'this package'),
                'object': dl['ifc']['object'], 'bytes': dl['ifc']['bytes'], 'sha256': dl['ifc']['sha256'],
                'sha256_checked_against': ('model_id (IFC models are content-addressed by the sha256 of their IFC)'
                                           if exp == ID else ('job.source_ifc_sha256' if exp else None)),
                'shipped_here': False,
                'note': 'the package\'s own IFC (converted_from) is the source; it is not copied into scripts/ because it '
                        'already ships in the package',
                **{k: job[k] for k in ('converted_from', 'converted_from_package', 'converter') if k in job}}
        else:
            src = ifc_spec['path']
            shutil.copyfile(src, ifc_local)
            got = C.file_sha256(ifc_local)
            if ifc_spec.get('sha256') and got != ifc_spec['sha256']:
                raise C.DownloadError(f'source IFC on the volume sha256 {got} != source stage {ifc_spec["sha256"]}')
            dl['ifc'] = {'bytes': os.path.getsize(ifc_local), 'sha256': got, 'object': src}
            log(f'source IFC from volume {src} sha256 {got[:12]}')
        rcs['download'] = 0
    except Exception as e:
        log(f'download error {e}')
        dl['error'] = str(e)
        rcs['download'] = 1
    e2e_inputs = None
    if rcs['download'] == 0:
        kit = os.path.join(CODE, 'kit')
        rcs['extract+exact'] = run_step('extract+exact', 'extract.log', [PY, '-c',
            "import sys, json; sys.path.insert(0, 'tools'); import extract, exact; i = extract.extract(sys.argv[1], sys.argv[2]); "
            "exact.main(sys.argv[2], sys.argv[3]); print(json.dumps(i['status']), json.dumps(i.get('exact_faces')))",
            ifc_local, O, step_local])
        rcs['props'] = run_step('props', 'extract.log', [PY, 'tools/props.py', ifc_local, O])
        rcs['recover'] = run_step('recover', 'recover.log', [PY, 'tools/recover.py', O, '--jobs', str(J), '--ifc', ifc_local,
                                                             '--step', step_local, '--time-budget', '1800', '--mem-budget-gb', '6'])
        rcs['views'] = run_step('views', 'views.log', [PY, 'tools/views.py', O])
        rcs['verify'] = run_step('verify', 'verify.log', [PY, 'tools/verify.py', O, step_local, '--ifc', ifc_local, '--jobs', str(J)])
        rcs['reference_defects'] = run_step('reference_defects', 'refdefects.log', [PY, 'tools/reference_defects.py', O, '--ifc', ifc_local])
        rcs['verify_levels'] = run_step('verify_levels', 'levels.log', [PY, 'tools/verify_levels.py', O, ifc_local])
        rcs['tekla_checks'] = run_step('tekla_checks', 'tekla.log', [PY, 'tools/tekla_checks.py', O, '--ifc', ifc_local, '--jobs', str(J),
                                                                     '--kit', kit, '--stem', STEM])
        # end-to-end: the packaged script run exactly as a user would, from a package-shaped folder
        E = os.path.join(W, 'e2e', STEM, 'scripts', 'model')
        os.makedirs(os.path.join(E, 'schedules'), exist_ok=True)
        shutil.copy(os.path.join(kit, 'steelbuild.py'), os.path.join(W, 'e2e', STEM, 'scripts'))
        shutil.copy(os.path.join(kit, 'build_model.py'), E)
        if os.path.exists(os.path.join(O, 'verification.csv')):
            shutil.copy(os.path.join(O, 'verification.csv'), E)
        for f in SCHEDULE_FILES:
            if os.path.exists(os.path.join(O, f)):
                shutil.copy(os.path.join(O, f), os.path.join(E, 'schedules'))
        # what e2e runs, byte for byte (the package stage ships exactly these bytes; it checks them against this list)
        e2e_inputs = _sha_tree(os.path.join(W, 'e2e', STEM, 'scripts'))
        rcs['e2e'] = run_step('e2e', 'e2e.log', [PY, 'tools/e2e.py', E, '--jobs', str(J), '--sample', '15'])
        for f in ('e2e_results.csv', 'e2e_summary.json'):
            if os.path.exists(os.path.join(E, f)):
                shutil.copy(os.path.join(E, f), O)
    summ = make_verdict(O)(rcs)
    ci = C.container_info(cls)
    summ.update(id=ID, gen=GEN, stem=STEM, pid=job.get('pid'), step=job.get('step'), ifc=job.get('ifc'), bytes=job.get('bytes'),
                cls=cls, tool=job.get('tool'), J=J, code=job.get('code_version'), host=ci['host'],
                iid=ci['task_id'], region=ci['region'], itype=f'modal:{res["cpu"]}cpu/{res["mem_gib"]}GiB',
                seconds=round(time.time() - t_start, 1), finished=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    peak, peak_how = mem.done()
    summ['peak_rss_gb'] = peak
    json.dump(summ, open(os.path.join(O, 'pmx_summary.json'), 'w'), indent=1)
    shutil.copy(LOG, os.path.join(O, 'pmx_job.log'))
    log(f'done perfect={summ["perfect"]} reasons={summ["reasons"]} {summ["seconds"]}s')

    # ---- publish to the volume
    P = os.path.join(JD, 'publish')
    os.makedirs(P)
    shutil.copytree(O, os.path.join(P, 'out'))
    C.write_json(os.path.join(P, 'summary.json'), summ)
    C.write_json(os.path.join(P, 'e2e_inputs.json'), {'code_version': job['code_version'], 'code_md5sums': md5,
                                                       'files': e2e_inputs})
    C.publish(P, os.path.join(MD, publish_rel))
    if source_rec is not None and publish_rel == 'pipeline':
        S = os.path.join(JD, 'source')
        os.makedirs(S)
        C.write_json(os.path.join(S, 'provenance.json'), source_rec)
        C.publish(S, os.path.join(MD, 'source'))
    killed = [k for k, v in rcs.items() if v in MEMORY_KILL_RCS]
    st = {}
    try:
        for line in open(os.path.join(O, 'step_times.tsv')).read().splitlines()[1:]:
            a = line.split('\t')
            st[a[0]] = float(a[2])
    except Exception:
        pass
    shutil.rmtree(JD, ignore_errors=True)
    return {'ok': rcs.get('download') == 0, 'stage': 'pipeline', 'cls': cls, 'J': J, 'code': job.get('code_version'),
            'error': dl.get('error'), 'perfect': summ['perfect'], 'reasons': summ['reasons'], 'status': summ.get('status'),
            'parts': summ.get('parts'), 'steps': rcs, 'step_seconds': st, 'download': dl, 'memory_killed_steps': killed,
            'seconds': summ['seconds'], 'cpu_seconds': cpu.done(), 'peak_gib': peak, 'peak_how': peak_how, 'container': ci,
            'source': source_rec and {k: source_rec[k] for k in ('sha256', 'sha256_checked_against', 'object')}}
