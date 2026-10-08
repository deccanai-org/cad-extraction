#!/usr/bin/env python3
"""pmx job: the v9 parametric pipeline for ONE model, run by worker.py in its own session (setsid).

  download STEP + IFC -> extract+exact -> props -> recover -> views -> verify -> reference_defects -> verify_levels
  -> tekla_checks -> e2e  ->  upload out/ to _state/pm_full/out/<id>/  ->  done marker _state/pm_full/done/<id>.g<gen>.json

Same steps, arguments and order as tools/cloud_pipeline.sh (v9) minus kiss_check (fabricator lists are project-level and
not joined to a model here). Every step has a timeout; a failed or timed-out step is recorded (rc) and the next steps
still run. The job heartbeats hb/<id> every 2 min so a dead box's claim can be taken over.

usage: job.py JOBDIR        (JOBDIR/job.json written by worker.py)
"""
import json, os, shutil, socket, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
import boto3, botocore
from boto3.s3.transfer import TransferConfig

B = 'bim-proprietary-data'
ST = 'cad-disk-extract/_state/pm_full/'
PKG = 'cad-disk-extract/dataset/packages/3d/'
PY = '/opt/pm/venv/bin/python'
s3 = boto3.client('s3', region_name='ap-south-1',
                  config=botocore.config.Config(retries={'max_attempts': 8, 'mode': 'standard'}, max_pool_connections=16,
                                                connect_timeout=10, read_timeout=120, tcp_keepalive=True))

JD = sys.argv[1]
LOCAL = os.environ.get('PMX_LOCAL') == '1'      # bench mode: no heartbeat / upload / done marker; out/ kept in JD/w
job = json.load(open(os.path.join(JD, 'job.json')))
ID, GEN, J, CODE = job['id'], job['gen'], int(job['J']), job['code_dir']
STEM = ID[:16]
W = os.path.join(JD, 'w')
O = os.path.join(W, 'out', STEM)
SRC = os.path.join(W, 'src')
LOG = os.path.join(JD, 'job.log')
# per-step timeout (s) by size class; recover has its own --time-budget
TMO = {'S': 3600, 'M': 7200, 'L': 4 * 3600, 'XL': 8 * 3600, 'XXL': 20 * 3600, 'XXXL': 30 * 3600}[job['cls']]
state = {'step': 'start', 'stop': False}


def log(msg):
    with open(LOG, 'a') as f:
        f.write(time.strftime('%H:%M:%S ') + msg + '\n')


def heartbeat():
    while not state['stop'] and not LOCAL:
        try:
            s3.put_object(Bucket=B, Key=f'{ST}hb/{ID}', Body=json.dumps(
                {'host': socket.gethostname(), 'iid': job.get('iid'), 'step': state['step'], 't': time.time()}).encode())
        except Exception as e:
            log(f'hb error {e!r}')
        for _ in range(120):
            if state['stop']:
                return
            time.sleep(1)


def run_step(name, logname, cmd, cwd=None, timeout=TMO):
    state['step'] = name
    t0 = time.time()
    with open(os.path.join(O, logname), 'a') as lf:
        try:
            p = subprocess.Popen(cmd, cwd=cwd or CODE, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 start_new_session=True, env=dict(os.environ, EXACT_JOBS=str(J)))
            try:
                rc = p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, 9)
                p.wait()
                rc = 124
                lf.write(f'\nTIMEOUT after {timeout}s\n')
        except Exception as e:
            lf.write(f'\nLAUNCH ERROR {e!r}\n')
            rc = 127
    dt = time.time() - t0
    with open(os.path.join(O, 'step_times.tsv'), 'a') as f:
        f.write(f'{name}\t{rc}\t{dt:.3f}\n')
    log(f'{name} rc={rc} {dt:.0f}s')
    return rc


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


def upload_dir(src, prefix):
    files = []
    for root, _, fs in os.walk(src):
        for f in fs:
            p = os.path.join(root, f)
            files.append((p, prefix + os.path.relpath(p, src)))
    def up(a):
        for i in range(5):
            try:
                s3.upload_file(a[0], B, a[1])
                return 0
            except Exception as e:
                log(f'upload retry {a[1]} {e!r}')
                time.sleep(5 * (i + 1))
        return 1
    with ThreadPoolExecutor(8) as ex:
        return sum(ex.map(up, files)), len(files)


def main():
    t_start = time.time()
    os.makedirs(O, exist_ok=True)
    os.makedirs(SRC, exist_ok=True)
    with open(os.path.join(O, 'step_times.tsv'), 'w') as f:
        f.write('step\texit_code\tseconds\n')
    threading.Thread(target=heartbeat, daemon=True).start()
    log(f'start {ID} gen {GEN} cls {job["cls"]} J {J} code {CODE}')
    # inputs straight from the package
    state['step'] = 'download'
    step_local = os.path.join(SRC, STEM + '.step')
    ifc_local = os.path.join(SRC, STEM + ('.ifczip' if job['ifc'].lower().endswith('.ifczip') else '.ifc'))
    rcs = {}
    try:
        tc = TransferConfig(max_concurrency=16, multipart_chunksize=64 * 1024 * 1024)
        # inputs from the package; a job may name full keys instead (step_key / ifc_key: e.g. the IFC regenerated from a
        # DB1 / SDS/2 model by our own converter, which the package does not hold)
        s3.download_file(B, job.get('step_key') or PKG + job['pid'] + '/' + job['step'], step_local, Config=tc)
        s3.download_file(B, job.get('ifc_key') or PKG + job['pid'] + '/' + job['ifc'], ifc_local, Config=tc)
        rcs['download'] = 0
    except Exception as e:
        log(f'download error {e!r}')
        rcs['download'] = 1
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
        for f in ('parts.csv', 'profiles.csv', 'profile_outlines.json', 'solids.csv', 'cuts.csv', 'cut_boundaries.json',
                  'openings.csv', 'paths.json', 'exact_geometry.jsonl', 'assemblies.csv'):
            if os.path.exists(os.path.join(O, f)):
                shutil.copy(os.path.join(O, f), os.path.join(E, 'schedules'))
        rcs['e2e'] = run_step('e2e', 'e2e.log', [PY, 'tools/e2e.py', E, '--jobs', str(J), '--sample', '15'])
        for f in ('e2e_results.csv', 'e2e_summary.json'):
            if os.path.exists(os.path.join(E, f)):
                shutil.copy(os.path.join(E, f), O)
    state['step'] = 'upload'
    summ = verdict(rcs)
    summ.update(id=ID, gen=GEN, stem=STEM, pid=job['pid'], step=job['step'], ifc=job['ifc'], bytes=job['bytes'],
                cls=job['cls'], tool=job.get('tool'), J=J, code=job.get('code_version'), host=socket.gethostname(),
                iid=job.get('iid'), region=job.get('region'), itype=job.get('itype'), seconds=round(time.time() - t_start, 1),
                finished=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    try:
        summ['peak_rss_gb'] = json.load(open(os.path.join(JD, 'peak.json'))).get('peak_rss_gb')
    except Exception:
        pass
    json.dump(summ, open(os.path.join(O, 'pmx_summary.json'), 'w'), indent=1)
    shutil.copy(LOG, os.path.join(O, 'pmx_job.log'))
    if LOCAL:
        json.dump(summ, open(os.path.join(JD, 'summary.json'), 'w'), indent=1)
        state['stop'] = True
        log(f'done (local) perfect={summ["perfect"]} reasons={summ["reasons"]} {summ["seconds"]}s')
        open(os.path.join(JD, 'FINISHED'), 'w').write('1')
        return
    bad, n = upload_dir(O, f'{ST}out/{ID}/')
    summ['uploaded'] = n
    summ['upload_errors'] = bad
    if bad:
        summ['perfect'] = False
        summ['reasons'].append('upload_errors')
    s3.put_object(Bucket=B, Key=f'{ST}done/{ID}.g{GEN}.json', Body=json.dumps(summ).encode())
    state['stop'] = True
    log(f'done perfect={summ["perfect"]} reasons={summ["reasons"]} {summ["seconds"]}s')
    shutil.rmtree(W, ignore_errors=True)
    open(os.path.join(JD, 'FINISHED'), 'w').write('1')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log(f'FATAL {e!r}')
        state['stop'] = True
        raise
