"""stage.py - the src_db1 stage driver (container side; standard library only, runs in the stage image's own python).

DB1 -> faithful source IFC for one DB1-sourced partial-tier model:
  inputs   pre-signed GET URLs (never logged): the package DB1, the delivered (package) STEP, and the conversion fleet's detail
           files (results JSON, src_parts census, decoded_parts) when the job has them
  work     regen_core.py (decoder conda env): regenerate the IFC with the kit that produced the shipped STEP (kit v / u,
           md5-pinned), prove the STEP stage reproduces the shipped STEP line for line, restore the shipped GlobalIds,
           prove again on the restored IFC; db1_facts.py: the decoder's skipped records with their source geometry
  outputs  source/model.ifc (only when reproduced), source/provenance.json (always), source/skipped_records.json (whenever
           the pinned kit decodes the DB1), logs/

Host requirement (checked first, before any download): an x86-64 CPU with AVX-512 (F, CD, BW, DQ, VL). The numbers the
decoder and the STEP stage write depend on the numeric kernels numpy / OpenBLAS dispatch for the host CPU; the shipped STEPs
reproduce only with the AVX-512 kernels (or the AVX2 ones emulated on an AVX-512 host), never on an AVX2-only host
(tests/results/diag_cpu_repro.json). About two thirds of unpinned Modal CPU containers are AVX2-only (AMD Zen 3,
tests/results/cpu_census.json); Modal refuses cloud pinning in this workspace but accepts region= ('ap-southeast': 8 of 9
draws AVX-512). An unsuitable host is reported, never treated as a model failure:
  run_standalone()  returns verdict 'host_unsuitable' (retryable=True, nothing downloaded, nothing written but logs)
  run()             (plug-in) calls modal.experimental.stop_fetching_inputs() (this container takes no further input, so
                    the caller's next call draws a new container) and returns {'ok': False, 'retryable': True,
                    'verdict': 'host_unsuitable', 'error': 'host_unsuitable: ...', 'host_cpu': {...}}; ctx['out'] stays
                    empty. The CALLER must re-call the stage for retryable results (the app's orchestrator does not yet:
                    see README "App integration"). Raising instead does not work: Modal re-raises a BaseException in
                    the caller (it escapes `except Exception`), and an Exception is recorded by run_plugin as a final
                    source failure (tests/results/baseexc_retry.json).

Entry points
  run(job, ctx)                plug-in contract (app/pmpstages plugins: ctx['work'], ctx['out'], ctx['fetch'], ctx['log'], ...):
                               writes model.ifc / provenance.json / skipped_records.json straight into ctx['out'];
                               the regeneration log is streamed into ctx['log']
  run_standalone(job, work, out, log=print, deadline=None)
                               the same, writing out/source/... and out/logs/...; returns the stage result dict

Job (accepted shapes; the jobs component's rows, jobs/new5.jsonl, plus a 'urls' dict from presign):
  model_id | id               DB1 sha256 = model id
  urls{...}                    pre-signed GET URLs. DB1: urls.db1 | urls.source | urls.src;  delivered STEP: urls.step;
                               results JSON: urls.results_json | urls['detail/results_json'] | urls.result | urls.results;
                               per-product census of the conversion IFC: urls.src_parts | urls['detail/src_parts'] (|
                               urls.census when that URL is a .src_parts.jsonl.gz); decoder parts list: urls.decoded_parts |
                               urls['detail/decoded_parts']
  bytes / step.bytes, step.sha256 (delivered STEP checks), source.key / step.key / detail_keys{} (S3 keys, provenance only),
  pin.kit / pin.code / converter.code (cross-checked against the kit regen_core selects from the shipped STEP)
"""
import hashlib, json, os, shutil, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cpu_facts  # noqa: E402  (standard library only)

CONV = os.environ.get('PMP_CONV_HOME', '/opt/conv')
PYE = f'{CONV}/env/bin/python'
PY84 = f'{CONV}/ifc84/bin/python'
STAGE_VERSION = 'pmp-src_db1-2026-10-07b'
URL_KEYS = {        # role -> accepted names in job['urls'] ('detail/<alias>' = the jobs component's presign.py naming)
    'db1': ('db1', 'source', 'src'),
    'step': ('step',),
    'result': ('results_json', 'detail/results_json', 'result', 'results'),
    'census': ('src_parts', 'detail/src_parts'),
    'decoded_parts': ('decoded_parts', 'detail/decoded_parts'),
}
DETAIL_KEYS = {'result': 'results_json', 'census': 'src_parts', 'decoded_parts': 'decoded_parts'}


class StageError(RuntimeError):
    pass


def stop_fetching_inputs():
    """inside a Modal container: take no further inputs (the retry then starts a new container, i.e. another host draw)"""
    try:
        import modal.experimental
        modal.experimental.stop_fetching_inputs()
        return True
    except Exception:
        return False


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def url_object(url):
    """bucket/key of a pre-signed URL without the query string (safe to log)"""
    try:
        u = urllib.parse.urlsplit(url)
        host = u.netloc.split('.')[0] if '.s3' in u.netloc else ''
        return urllib.parse.unquote((host + u.path) if host else u.path)
    except Exception:
        return '?'


def download(url, dest, nbytes=None, sha256=None, tries=6, log=print):
    """stream a pre-signed GET URL to dest (atomic), sha256 while streaming; URL-free error messages"""
    obj = url_object(url)
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    tmp = dest + '.part'
    last = None
    for i in range(tries):
        t0 = time.time()
        try:
            h, n = hashlib.sha256(), 0
            req = urllib.request.Request(url, headers={'User-Agent': 'pmp-src-db1/1'})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
                while True:
                    b = r.read(8 << 20)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    n += len(b)
            d = h.hexdigest()
            if nbytes is not None and n != int(nbytes):
                raise StageError(f'{obj}: got {n} bytes, expected {nbytes}')
            if sha256 and d != sha256:
                raise StageError(f'{obj}: sha256 {d} != expected {sha256}')
            os.replace(tmp, dest)
            log(f'downloaded {obj} {n} B sha256 {d[:16]} in {time.time() - t0:.1f}s')
            return {'object': obj, 'bytes': n, 'sha256': d, 'seconds': round(time.time() - t0, 1)}
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code in (400, 401, 403, 404):
                break
        except StageError as e:
            last = str(e)
            break
        except Exception as e:
            last = f'{type(e).__name__}: {str(e)[:200]}'
        log(f'download retry {i + 1} {obj}: {last}')
        time.sleep(min(60, 5 * (i + 1)))
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise StageError(f'download failed for {obj}: {last}')


def pick_url(urls, role):
    for k in URL_KEYS[role]:
        if urls.get(k):
            return urls[k]
    if role == 'census' and urls.get('census') and '.src_parts.jsonl.gz' in url_object(urls['census']):
        return urls['census']
    return None


def normalise(job):
    j = dict(job)
    mid = j.get('model_id') or j.get('id')
    if not mid:
        raise StageError('job without model_id')
    urls = dict(j.get('urls') or {})
    for k in ('db1', 'step'):
        if j.get(k + '_url') and k not in urls:
            urls[k] = j[k + '_url']
    # jobs component rows carry step / source dicts; the app's normalised jobs move them to step_info / source_info
    step = j.get('step') if isinstance(j.get('step'), dict) else (j.get('step_info') or {})
    src = j.get('source') if isinstance(j.get('source'), dict) else (j.get('source_info') or {})
    det = j.get('detail_keys') or {}
    keys = {'db1': src.get('key') or (j.get('keys') or {}).get('db1'), 'step': step.get('key') or (j.get('keys') or {}).get('step')}
    for role, alias in DETAIL_KEYS.items():
        keys[role] = det.get(alias) or (j.get('keys') or {}).get(role)
    pin = j.get('pin') or {}
    conv = j.get('converter') or pin.get('converter') or {}
    relpath = j.get('relpath') or (j['step'] if isinstance(j.get('step'), str) else None)
    return {'model_id': mid, 'pid': j.get('pid'), 'relpath': relpath, 'tag': j.get('tag'),
            'bytes': step.get('bytes') or j.get('bytes'), 'step_sha256': step.get('sha256') or j.get('step_sha256'),
            'db1_bytes': src.get('bytes') or j.get('db1_bytes'), 'urls': urls, 'keys': keys,
            'converter_code': conv.get('code') or pin.get('code') or j.get('converter_code'),
            'kit_pin_from_jobs': pin.get('kit'), 'engine_from_jobs': pin.get('engine')}


class Peak:
    """peak memory of this container (cgroup v2 memory.peak / v1 max_usage, else summed RSS samples of the process tree)"""

    def __init__(self, every=2.0):
        self.cg = next((p for p in ('/sys/fs/cgroup/memory.peak', '/sys/fs/cgroup/memory/memory.max_usage_in_bytes')
                        if os.path.exists(p)), None)
        self.peak, self.stop, self.every = 0.0, False, every
        threading.Thread(target=self._loop, daemon=True).start()

    def _rss_tree(self):
        tot = 0
        for pid in os.listdir('/proc'):
            if pid.isdigit():
                try:
                    for line in open(f'/proc/{pid}/status'):
                        if line.startswith('VmRSS:'):
                            tot += int(line.split()[1]) * 1024
                            break
                except Exception:
                    pass
        return tot

    def sample(self):
        if self.cg:
            try:
                return int(open(self.cg).read().split()[0]) / 2**30
            except Exception:
                pass
        try:
            return self._rss_tree() / 2**30
        except Exception:
            return 0.0

    def _loop(self):
        while not self.stop:
            self.peak = max(self.peak, self.sample())
            time.sleep(self.every)

    def done(self):
        self.stop = True
        self.peak = max(self.peak, self.sample())
        return round(self.peak, 2), ('cgroup' if self.cg else 'rss_samples')


def decoder_env():
    """environment for the decoder / STEP subprocesses: the container's, minus whatever points python at foreign packages
    (the Modal runtime sets PYTHONPATH to its own client packages; production ran the kit with none of them)"""
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE',
                                                           'PYTHONNOUSERSITE', 'VIRTUAL_ENV', 'CONDA_PREFIX')}
    env['PYTHONHASHSEED'] = '0'
    env['PYTHONNOUSERSITE'] = '1'
    return env


def kill_conv_tree():
    """kill every process of the decoder envs (regen_core starts its decoder / STEP children in their own sessions)"""
    me = os.getpid()
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            cmd = open(f'/proc/{pid}/cmdline', 'rb').read().replace(b'\0', b' ')
        except Exception:
            continue
        if CONV.encode() in cmd or b'/pmp/src_db1/' in cmd:
            try:
                os.kill(int(pid), 9)
            except Exception:
                pass


def run_standalone(job, work, out, log=print, deadline=None):
    """-> result dict {ok, verdict, reason, kit, ifc{path,bytes,sha256}, skipped_records{...}, seconds, downloads, ...}"""
    t0 = time.time()
    J = normalise(job)
    mid = J['model_id']
    os.makedirs(work, exist_ok=True)
    os.makedirs(os.path.join(out, 'source'), exist_ok=True)
    os.makedirs(os.path.join(out, 'logs'), exist_ok=True)
    rec = {'stage': 'src_db1', 'stage_version': STAGE_VERSION, 'model_id': mid, 'tag': J.get('tag'), 'ok': False,
           'verdict': None, 'reason': None, 'downloads': {}}
    peak = Peak()
    host = cpu_facts.facts(PY84, decoder_env())
    rec['host_cpu'] = host
    log(f"host cpu {host.get('vendor')} family {host.get('family')} model {host.get('model')} avx512={host.get('avx512')} "
        f"numpy={host.get('numpy')} openblas={host.get('openblas_core')}")
    if not host.get('avx512'):
        rec.update(verdict='host_unsuitable', retryable=True,
                   reason=f"host CPU {host.get('vendor')} family {host.get('family')} model {host.get('model')} has no AVX-512 "
                          f"(flags {host.get('flags')}): the shipped STEP cannot be reproduced here; retry on another container")
        rec['peak_gib'], rec['peak_how'] = peak.done()
        rec['seconds'] = round(time.time() - t0, 1)
        rec['nproc'] = os.cpu_count()
        json.dump(rec, open(os.path.join(out, 'logs', 'src_db1_stage.json'), 'w'), indent=1, default=str)
        return rec
    try:
        files = {}
        ind = os.path.join(work, 'in')
        for role in ('db1', 'step', 'result', 'census', 'decoded_parts'):
            url = pick_url(J['urls'], role)
            if not url:
                if role in ('db1', 'step'):
                    raise StageError(f'job has no pre-signed URL for the {role}')
                files[role] = None
                rec['downloads'][role] = None
                continue
            name = {'db1': 'in.db1', 'step': 'shipped.step', 'result': 'result.json', 'census': 'src_parts.jsonl.gz',
                    'decoded_parts': 'decoded_parts.json.gz'}[role]
            kw = {}
            if role == 'db1':
                kw = {'sha256': mid, 'nbytes': J.get('db1_bytes')}       # the DB1 sha256 IS the model id
            elif role == 'step':
                kw = {'nbytes': J.get('bytes'), 'sha256': J.get('step_sha256')}
            dl = download(url, os.path.join(ind, name), log=log, **kw)
            files[role] = os.path.join(ind, name)
            rec['downloads'][role] = {k: dl[k] for k in ('object', 'bytes', 'sha256', 'seconds')}
        rj = {'model_id': mid, 'pid': J['pid'], 'step_relpath': J['relpath'], 'converter_code': J['converter_code'],
              'files': files, 'keys': J['keys'], 'step_bytes': J['bytes'], 'db1_bytes': J['db1_bytes'],
              'deadline': (deadline - 120) if deadline else None}
        jf = os.path.join(work, 'JOB.json')
        json.dump(rj, open(jf, 'w'), indent=1)
        timeout = None if deadline is None else max(60, int(deadline - time.time()))
        cmd = [PYE, os.path.join(HERE, 'regen_core.py'), jf, os.path.join(work, 'regen'), out]
        log('regen_core start')
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=decoder_env())
        try:
            so, se = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_conv_tree()
            p.kill()
            p.communicate()
            raise StageError('regen_core.py did not finish before the stage deadline (killed with its decoder / STEP children)')
        lines = [l for l in so.strip().splitlines() if l.startswith('{')]
        res = json.loads(lines[-1]) if lines else None
        if p.returncode != 0 or res is None:
            raise StageError(f'regen_core.py rc {p.returncode}: {(so + se)[-1500:]}')
        prov = json.load(open(os.path.join(out, 'source', 'provenance.json')))
        rec.update(verdict=res['verdict'], reason=res.get('reason'), kit=res.get('kit'), profile=res.get('profile'),
                   attempts=res.get('attempts'), retryable=res['verdict'] == 'host_unsuitable',
                   ifc=prov.get('ifc'), kit_selection=prov.get('kit_selection'), engine=prov.get('engine'),
                   skipped_records={k: v for k, v in (prov.get('skipped_records') or {}).items() if k != 'proof'},
                   proof=prov.get('proof'), guids={k: v for k, v in (prov.get('guids') or {}).items() if k != 'derived'})
        sr = prov.get('skipped_records') or {}
        rec['skipped_records_proof'] = sr.get('proof')
        if J.get('kit_pin_from_jobs') and res.get('kit') and J['kit_pin_from_jobs'] != res['kit']:
            rec['kit_pin_note'] = f"jobs pinned {J['kit_pin_from_jobs']}, reproduced with {res['kit']}"
        rec['ok'] = res['verdict'] == 'reproduced'
    except Exception as e:
        rec['ok'] = False
        rec['verdict'] = rec['verdict'] or 'fail'
        rec['reason'] = f'{type(e).__name__}: {e}'
        # never leave an IFC next to a failed verdict
        p = os.path.join(out, 'source', 'model.ifc')
        if os.path.exists(p):
            os.remove(p)
    rec['peak_gib'], rec['peak_how'] = peak.done()
    rec['seconds'] = round(time.time() - t0, 1)
    rec['nproc'] = os.cpu_count()
    json.dump(rec, open(os.path.join(out, 'logs', 'src_db1_stage.json'), 'w'), indent=1, default=str)
    return rec


def run(job, ctx):
    """plug-in contract: ctx['out'] receives model.ifc / provenance.json / skipped_records.json (published as /<id>/source/)"""
    log = ctx.get('log') or print
    work = ctx['work']
    stage_out = os.path.join(work, 'stage_out')
    rec = run_standalone(job, os.path.join(work, 'w'), stage_out, log=log, deadline=ctx.get('deadline'))
    if rec.get('verdict') == 'host_unsuitable':
        stopped = stop_fetching_inputs()
        log(f"host_unsuitable: {rec.get('reason')} (container stops taking inputs: {stopped}); retryable - call again")
        rec.update(ok=False, retryable=True, ifc=None, sha256=None, provenance=None,
                   error=f"host_unsuitable: {rec.get('reason')}", container_stops_taking_inputs=stopped)
        return rec
    for fn in ('model.ifc', 'provenance.json', 'skipped_records.json'):
        p = os.path.join(stage_out, 'source', fn)
        if os.path.exists(p):
            shutil.copyfile(p, os.path.join(ctx['out'], fn))
    lp = os.path.join(stage_out, 'logs', 'src_db1.log')
    if os.path.exists(lp):
        with open(lp, errors='replace') as f:
            for line in f.read().splitlines()[-400:]:
                log('regen| ' + line[:400])
    rec['ifc'] = 'model.ifc' if rec['ok'] else None
    rec['sha256'] = sha256_file(os.path.join(ctx['out'], 'model.ifc')) if rec['ok'] else None
    rec['provenance'] = json.load(open(os.path.join(ctx['out'], 'provenance.json'))) if os.path.exists(
        os.path.join(ctx['out'], 'provenance.json')) else None
    rec['error'] = None if rec['ok'] else (rec.get('reason') or rec.get('verdict'))
    return rec
