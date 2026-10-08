"""src_sds2 stage: a faithful source IFC for one SDS/2-converted model of the partial tier, emitted from the packaged
SDS/2 job by the very converter build that wrote the shipped STEP, with proof (standard library only; runs inside the
pmp-src-sds2 image, see modal_sds2.py).

    run(job, ctx) -> dict           (the plug-in contract of app/: ctx['work'], ctx['out'], ctx['log'], ctx['J'],
                                     ctx['deadline'], optional ctx['fetch'])

Steps (each timed; any failure is recorded with its reason, nothing is retried silently, no IFC leaves a run that did not
reproduce the shipped STEP):
  1 pin        the converter build: job['converter_pin'] (from pin.py on the Mac) or pin.resolve_pin(job, result JSON
               from urls.sds2_result); its zip must be in the image with the pinned sha256 (checked on every run)
  2 fetch      shipped STEP (urls.step) and the package's SDS/2 job zip (urls.sds2) via pre-signed GET URLs; sizes and
               sha256 checked against the package manifest values in the job when given; the URLs are never logged
  3 convert    decode/sds2_to_step.py JOB -o OUT --stage 2 --verify, exactly as the conversion fleet ran it, in the
               converter env (/opt/conv: python 3.12 + the converters' pinned pip set), the job folder linked under the
               shipped STEP's root product name, with the IFC emitter 1.1 + facts hooks installed (emitter/emit_run.py)
  4 compare    the STEP written vs the shipped STEP: byte for byte below the FILE_NAME line, and FILE_NAME with only its
               time stamp blanked (the converter's one variable field) -> step_identical
  5 emit check the emitter's own report: every instance emitted, nothing unsupported, no hook error
  6 prove      proofkit/prove_labels.py in the pipeline env (/opt/pipe: the fleet's python 3.11 requirements, code_sds2):
               every instance label of the shipped STEP <-> the IFC product of the same GlobalId, volume / centre / bbox
               within TOL_SRC_* and IFC Name == STEP label -> reproduced
  7 facts      facts_build.py -> sds2_facts.json (pieces / builders / stand-ins / skipped pieces with source geometry /
               members without geometry / bolts / cut holes per instance)
Outputs in ctx['out'] (only when step_identical and reproduced): model.ifc, provenance.json, sds2_facts.json,
reproduction.csv.gz, converter/ (the converter's own pieces.csv, skipped.csv, manifest.json (v5.x), preview.png,
convert.log, ifc_emit.json, ifc_products.jsonl). On failure: provenance.json (ok false, the evidence) + converter/ only.
"""
import gzip, hashlib, json, mmap, os, platform, re, shutil, subprocess, sys, time, traceback, urllib.error, \
    urllib.parse, urllib.request, zipfile

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
CONV_DIR = os.environ.get('PMP_SDS2_CONVERTERS', os.path.join(SRC, 'converters'))
CONV_PY = os.environ.get('PMP_CONV_PY', '/opt/conv/bin/python')
PIPE_PY = os.environ.get('PMP_PIPE_PY', '/opt/pipe/bin/python')
PROOF_CODE = os.path.join(SRC, 'proofkit', 'code_sds2')
STAGE_VERSION = 'pmp-src-sds2 1.0'
EMITTER = ('z3-sds2-ifc-emitter', '1.1')


class StageError(RuntimeError):
    def __init__(self, verdict, msg):
        super().__init__(msg)
        self.verdict = verdict


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------------- downloads
def url_object(url):
    try:
        u = urllib.parse.urlsplit(url)
        return urllib.parse.unquote(u.netloc.split('.')[0] + u.path) if '.s3' in u.netloc else urllib.parse.unquote(u.path)
    except Exception:
        return '?'


def download(url, dest, sha256=None, nbytes=None, tries=6, log=print):
    """stream a pre-signed GET URL to dest (sha256 while streaming, atomic rename); 4xx -> no retry. URL never logged."""
    obj = url_object(url)
    tmp = dest + '.part'
    last = None
    for i in range(tries):
        t0 = time.time()
        try:
            h, n = hashlib.sha256(), 0
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'pmp-src-sds2/1'}), timeout=120) as r, \
                    open(tmp, 'wb') as f:
                while True:
                    b = r.read(8 << 20)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    n += len(b)
            d = h.hexdigest()
            if nbytes is not None and n != int(nbytes):
                raise StageError('input_mismatch', f'{obj}: got {n} bytes, manifest says {nbytes}')
            if sha256 and d != sha256:
                raise StageError('input_mismatch', f'{obj}: sha256 {d} != manifest {sha256}')
            os.replace(tmp, dest)
            log(f'downloaded {obj} {n} B sha256 {d[:12]} in {time.time() - t0:.1f}s')
            return {'bytes': n, 'sha256': d, 'object': obj}
        except StageError:
            raise
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if 400 <= e.code < 500:
                break
        except Exception as e:
            last = f'{type(e).__name__}: {str(e)[:200]}'
        log(f'download retry {i + 1} {obj}: {last}')
        time.sleep(min(60, 5 * (i + 1)))
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise StageError('download_failed', f'download failed for {obj}: {last}')


# ---------------------------------------------------------------------------------------------------- STEP helpers
def _args(text):
    body = text[text.index('(') + 1:text.rindex(')')]
    out, depth, cur, q = [], 0, [], False
    for ch in body:
        if q:
            cur.append(ch)
            if ch == "'":
                q = False
            continue
        if ch == "'":
            q = True
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            out.append(''.join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    out.append(''.join(cur).strip())
    return out


def _unstr(t):
    t = t.strip()[1:-1].replace("''", "'")
    t = re.sub(r'\\X2\\([0-9A-F]+)\\X0\\', lambda q: ''.join(chr(int(q.group(1)[k:k + 4], 16)) for k in range(0, len(q.group(1)), 4)), t)
    return re.sub(r'\\X\\([0-9A-F]{2})', lambda q: chr(int(q.group(1), 16)), t)


def root_name(step_path):
    """the converter's root assembly product name in the shipped STEP (= the job folder name the fleet converted);
    None when the STEP has no assembly (then the folder name does not reach the file)"""
    with open(step_path, 'rb') as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            def stmt(ref):
                k = mm.find(b'\n' + ref.encode() + b' = ')
                return mm[k + 1:mm.find(b';\n', k)].decode('latin-1').replace('\n', '') if k >= 0 else None
            i = mm.find(b'NEXT_ASSEMBLY_USAGE_OCCURRENCE(')
            if i < 0:
                return None
            nauo = mm[i:mm.find(b';\n', i)].decode('latin-1').replace('\n', '')
            pdf = _args(stmt(_args(nauo)[3]))[2]
            prod = _args(stmt(pdf))[2]
            return _unstr(_args(stmt(prod))[0])
        finally:
            mm.close()


def step_body(p):
    """sha256 of the file without its FILE_NAME statement, and that statement with its time stamp blanked"""
    with open(p, 'rb') as f:
        data = f.read()
    i = data.find(b'FILE_NAME(')
    j = data.find(b';', i)
    return hashlib.sha256(data[:i] + data[j:]).hexdigest(), re.sub(rb"'\d{4}-\d\d-\d\dT[\d:]+'", b"T", data[i:j])


def safe_extract(zpath, dest):
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        for n in names:
            if n.startswith('/') or '..' in n.replace('\\', '/').split('/'):
                raise StageError('input_unsafe', f'zip member with unsafe path: {n[:120]!r}')
        z.extractall(dest)
    return len(names)


def adapt_job(job):
    """the stage's own job contract (README "Job contract") from either that contract or the jobs component's rows /
    the app's normalised jobs (common.normalise_job): step_key <- conv.step_key; converter <- pin.converter;
    converter_pin <- pin {label, zip, zip_sha256, run}; step_sha256 / bytes <- step{} or step_info{}; sds2_sha256 /
    sds2_bytes / converted_from <- source{} or source_info{}; relpath <- step (string). Explicit keys always win."""
    j = dict(job)

    def put(k, v):
        if j.get(k) in (None, '') and v not in (None, ''):
            j[k] = v
    put('id', j.get('model_id'))
    conv = j.get('conv') if isinstance(j.get('conv'), dict) else {}
    if not (j.get('step_key') or j.get('source_key')):
        put('step_key', conv.get('step_key'))
    pj = j.get('pin') if isinstance(j.get('pin'), dict) else {}
    if isinstance(pj.get('converter'), dict):
        put('converter', pj['converter'])
    if not j.get('converter_pin') and pj.get('label') and pj.get('zip') and (pj.get('sha256') or pj.get('zip_sha256')):
        j['converter_pin'] = dict(label=pj['label'], zip=pj['zip'], sha256=pj.get('sha256') or pj.get('zip_sha256'),
                                  basis='job_pin' + (':' + str(pj['run']) if pj.get('run') else ''),
                                  evidence=pj.get('evidence'), checks=[])
    for k in ('step_info', 'step'):
        if isinstance(j.get(k), dict):
            put('step_sha256', j[k].get('sha256'))
            put('bytes', j[k].get('bytes'))
    for k in ('source_info', 'source'):
        if isinstance(j.get(k), dict):
            put('sds2_sha256', j[k].get('sha256'))
            put('sds2_bytes', j[k].get('bytes'))
            put('converted_from', j[k].get('relpath'))
    if isinstance(j.get('step'), str):
        put('relpath', j['step'])
    return j


def _redact(job):
    r = {k: v for k, v in job.items() if k != 'urls' and not str(k).endswith('_url')}
    r['url_objects'] = {k: url_object(v) for k, v in (job.get('urls') or {}).items() if isinstance(v, str)}
    return r


# ---------------------------------------------------------------------------------------------------- the stage
def _pin(job, work, fetch, log):
    import pin as PIN
    p = job.get('converter_pin')
    if p:
        p = dict(p)
        p.setdefault('basis', 'job')
        p['checks'] = list(p.get('checks') or [])
        try:                                     # independent cross-check with pin.py's own evidence order
            q = PIN.resolve_pin(job, None)
            if (q['label'], q['zip'], q['sha256']) != (p['label'], p['zip'], p['sha256']):
                raise StageError('pin_conflict', f'job pin {p["label"]} {p["zip"]} disagrees with pin.py '
                                 f'({q["label"]} {q["zip"]}, basis {q["basis"]})')
            p['checks'].append(f'pin.py agrees (basis {q["basis"]})')
        except PIN.PinError as e:
            p['checks'].append(f'pin.py could not cross-check: {e}')
    else:
        res = None
        if (job.get('urls') or {}).get('sds2_result'):
            rp = os.path.join(work, 'conv_result.json')
            fetch('sds2_result', rp)
            res = json.load(open(rp))
        p = PIN.resolve_pin(job, res)
    ent = PIN.TABLE['labels'].get(p['label'])
    if not ent or (ent['zip'], ent['sha256']) != (p['zip'], p['sha256']):
        raise StageError('pin_unknown', f'converter pin {p} is not the pinned build of converters.json ({ent})')
    zp = os.path.join(CONV_DIR, p['zip'])
    if not os.path.exists(zp):
        raise StageError('pin_missing_zip', f'converter zip {p["zip"]} is not in the image')
    got = sha256_file(zp)
    if got != p['sha256']:
        raise StageError('pin_zip_sha', f'converter zip {p["zip"]} sha256 {got} != pinned {p["sha256"]}')
    log(f'converter {p["label"]} {p["zip"]} sha256 {got[:12]} (basis {p["basis"]})')
    return p, zp


def run(job, ctx):
    t_start = time.time()
    job = adapt_job(job)
    log = ctx.get('log') or print
    work, out = ctx['work'], ctx['out']
    J = int(ctx.get('J') or 4)
    deadline = ctx.get('deadline') or (time.time() + 4 * 3600)
    mid = job.get('id') or job.get('model_id')
    urls = job.get('urls') or {}
    alias = {'sds2': ('sds2', 'source', 'sds2_zip', 'converted_from')}

    def fetch(key, dest, sha256=None, nbytes=None):
        for k in alias.get(key, (key,)):
            if urls.get(k):
                if ctx.get('fetch'):
                    return ctx['fetch'](k, dest, sha256=sha256, nbytes=nbytes)
                return download(urls[k], dest, sha256=sha256, nbytes=nbytes, log=log)
        raise StageError('input_missing', f'job has no urls.{key}')

    steps, rec = {}, dict(ok=False, error=None, verdict=None, stage_version=STAGE_VERSION, model_id=mid)
    prov = dict(source_kind='emitted_from_sds2', model_id=mid, stage=STAGE_VERSION,
                note='IFC emitted by our own SDS/2 converter (sds2-step-pipeline, the build that produced the shipped STEP) '
                     'from the same in-memory shapes its STEP writer wrote; the reproduction proof is therefore a consistency '
                     'check against our converter, not an independent source: whether the converter decoded SDS/2 correctly '
                     'is evidenced by its own grading (package manifest grader / partial record) and by sds2_facts.json',
                package=dict(pid=job.get('pid'), step=job.get('relpath'), sds2_job=job.get('converted_from'),
                             converter_manifest=job.get('converter')),
                job=_redact(job))
    conv_out = os.path.join(out, 'converter')
    os.makedirs(conv_out, exist_ok=True)

    def step(name):
        steps[name] = dict(t0=time.time())

    def done(name, **kw):
        steps[name].update(seconds=round(time.time() - steps[name].pop('t0'), 1), **kw)

    rundir = os.path.join(work, 'run')
    base = None
    try:
        if not mid:
            raise StageError('bad_job', 'job without id / model_id')
        step('pin')
        pinned, zp = _pin(job, work, fetch, log)
        prov['converter'] = dict(pinned, code=(job.get('converter') or {}).get('code'),
                                 version=(job.get('converter') or {}).get('version'))
        done('pin')
        # ---------------------------------------------------------------- fetch inputs
        step('fetch')
        shipped = os.path.join(work, 'shipped.step')
        st = fetch('step', shipped, sha256=job.get('step_sha256') or job.get('sha256'), nbytes=job.get('bytes'))
        jz = os.path.join(work, 'job.zip')
        sz = fetch('sds2', jz, sha256=job.get('sds2_sha256') or job.get('source_sha256'),
                   nbytes=job.get('sds2_bytes') or job.get('source_bytes'))
        jd = os.path.join(work, 'job')
        nmem = safe_extract(jz, jd)
        os.remove(jz)
        tops = sorted(x for x in os.listdir(jd) if not x.startswith('.'))
        if len(tops) != 1 or not os.path.isdir(os.path.join(jd, tops[0])):
            raise StageError('input_layout', f'SDS/2 zip holds {len(tops)} top entries ({tops[:4]}), expected one job folder')
        cd = os.path.join(work, 'conv')
        safe_extract(zp, cd)
        conv_root = os.path.join(cd, 'sds2-step-pipeline')
        if not os.path.exists(os.path.join(conv_root, 'decode', 'sds2_to_step.py')):
            raise StageError('pin_zip_layout', 'converter zip has no sds2-step-pipeline/decode/sds2_to_step.py')
        root = root_name(shipped)
        link_name = root or tops[0]
        ld = os.path.join(work, 'link')
        os.makedirs(ld, exist_ok=True)
        os.symlink(os.path.join(jd, tops[0]), os.path.join(ld, link_name))
        sk = job.get('step_key') or job.get('source_key') or ''
        oname = os.path.basename(sk) if sk.endswith('_stage2.step') else link_name.replace(' ', '_') + '_stage2.step'
        prov['inputs'] = dict(shipped_step=dict(st, step_key=sk or None), sds2_zip=dict(sz, members=nmem, job_folder=tops[0]),
                              root_product=root, job_link_name=link_name, out_name=oname)
        done('fetch', shipped_bytes=st['bytes'], sds2_zip_bytes=sz['bytes'])
        # ---------------------------------------------------------------- convert (+ IFC emitter + facts hooks)
        step('convert')
        os.makedirs(rundir, exist_ok=True)
        ostep = os.path.join(rundir, oname)
        base = os.path.splitext(ostep)[0]
        cmd = [CONV_PY, '-u', os.path.join(SRC, 'emitter', 'emit_run.py'), conv_root, os.path.join(ld, link_name),
               '-o', ostep, '--stage', '2', '--verify', '--model-id', mid, '--shipped-sha256', st['sha256'],
               '--converter', '%s %s %s' % (pinned['label'], pinned['zip'], pinned['sha256'])]
        env = {k: v for k, v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME')}
        env.update(MPLBACKEND='Agg', PYTHONDONTWRITEBYTECODE='1')
        left = deadline - time.time() - 300
        if left < 120:
            raise StageError('timeout', f'no time left to convert ({left:.0f}s)')
        clog = os.path.join(conv_out, 'convert.log')
        try:
            with open(clog, 'w') as lf:
                rc = subprocess.call(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=rundir, timeout=left)
        except subprocess.TimeoutExpired:
            raise StageError('timeout', f'converter still running after {left:.0f}s')
        done('convert', rc=rc)
        log(f'converter rc {rc} in {steps["convert"]["seconds"]}s')
        for suf, dst in (('_pieces.csv', 'pieces.csv'), ('_skipped.csv', 'skipped.csv'), ('_manifest.json', 'manifest.json'),
                         ('_preview.png', 'preview.png'), ('_ifc_emit.json', 'ifc_emit.json'),
                         ('_ifc_products.jsonl', 'ifc_products.jsonl'), ('_ifc_error.txt', 'ifc_error.txt'),
                         ('_facts_error.txt', 'facts_error.txt')):
            if os.path.exists(base + suf):
                shutil.copy(base + suf, os.path.join(conv_out, dst))
        if not os.path.exists(ostep):
            raise StageError('convert_failed', f'converter wrote no STEP (rc {rc}); see converter/convert.log')
        # ---------------------------------------------------------------- compare with the shipped STEP
        step('compare')
        a, fa = step_body(ostep)
        b, fb = step_body(shipped)
        rerun_sha = sha256_file(ostep)
        rr = dict(rc=rc, seconds=steps['convert']['seconds'], step_identical_below_file_name=(a == b),
                  file_name_same_but_time=(fa == fb), rerun_bytes=os.path.getsize(ostep), shipped_bytes=st['bytes'],
                  rerun_sha256=rerun_sha, shipped_sha256=st['sha256'],
                  method='sha256 of the file without its FILE_NAME statement equal, and FILE_NAME equal with its time stamp blanked')
        rr['step_identical'] = bool(rr['step_identical_below_file_name'] and rr['file_name_same_but_time'])
        prov['converter_rerun'] = rr
        done('compare', step_identical=rr['step_identical'])
        log(f'STEP identical below FILE_NAME: {rr["step_identical_below_file_name"]}; FILE_NAME same but time: {rr["file_name_same_but_time"]}')
        if not rr['step_identical']:
            raise StageError('step_not_reproduced', 'the pinned converter re-run did not reproduce the shipped STEP '
                             f'(rc {rc}, {rr["rerun_bytes"]} vs {rr["shipped_bytes"]} bytes)')
        # ---------------------------------------------------------------- emitter report
        step('emit_check')
        ifc = base + '.ifc'
        em = json.load(open(base + '_ifc_emit.json')) if os.path.exists(base + '_ifc_emit.json') else None
        if em is None or not os.path.exists(ifc):
            raise StageError('emit_failed', 'the IFC emitter did not run (no _ifc_emit.json / .ifc); see converter/')
        isha = sha256_file(ifc)
        if em.get('ifc_sha256') != isha:
            raise StageError('emit_failed', f'IFC sha256 {isha} != emitter report {em.get("ifc_sha256")}')
        prov['emitter'] = dict(name=EMITTER[0], version=EMITTER[1], reported=em.get('emitter_version'),
                               sds2ifc_sha256=sha256_file(os.path.join(SRC, 'emitter', 'sds2ifc.py')),
                               sds2label_sha256=sha256_file(os.path.join(SRC, 'emitter', 'sds2label.py')),
                               emit_run_sha256=sha256_file(os.path.join(SRC, 'emitter', 'emit_run.py')),
                               facts_hooks_sha256=sha256_file(os.path.join(SRC, 'emitter', 'facts_hooks.py')),
                               instances=em.get('instances'), instances_emitted=em.get('instances_emitted'),
                               unique_parts=em.get('unique_parts'), parts_with_holes=em.get('parts_with_holes'),
                               hole_tools=em.get('hole_tools'), classes=em.get('classes'),
                               duplicate_labels=em.get('duplicate_labels'), unsupported_count=em.get('unsupported_count'),
                               unsupported=(em.get('unsupported') or [])[:20], hook_errors=em.get('hook_errors'),
                               seconds=em.get('seconds'))
        problems = []
        if em.get('unsupported_count'):
            problems.append(f"{em['unsupported_count']} instance(s) not representable: {em.get('unsupported', [])[:2]}")
        if em.get('instances_emitted') != em.get('instances'):
            problems.append(f"{em.get('instances_emitted')} of {em.get('instances')} instances emitted")
        if em.get('hook_errors'):
            problems.append(f"emitter hook errors: {str(em['hook_errors'])[:300]}")
        done('emit_check', problems=problems)
        if problems:
            raise StageError('emit_incomplete', '; '.join(problems))
        # ---------------------------------------------------------------- per-instance reproduction proof
        step('prove')
        left = deadline - time.time() - 120
        if left < 60:
            raise StageError('timeout', f'no time left for the proof ({left:.0f}s)')
        pref = os.path.join(rundir, 'reproduction')
        plog = os.path.join(conv_out, 'prove.log')
        penv = {k: v for k, v in os.environ.items() if k not in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME')}
        try:
            with open(plog, 'w') as lf:
                prc = subprocess.call([PIPE_PY, '-u', os.path.join(SRC, 'proofkit', 'prove_labels.py'), PROOF_CODE, ifc,
                                       shipped, pref, '--jobs', str(J)], stdout=lf, stderr=subprocess.STDOUT, env=penv,
                                      cwd=rundir, timeout=left)
        except subprocess.TimeoutExpired:
            raise StageError('timeout', f'proof still running after {left:.0f}s')
        if prc != 0 or not os.path.exists(pref + '.json'):
            raise StageError('prove_failed', f'prove_labels.py rc {prc}; see converter/prove.log')
        pr = json.load(open(pref + '.json'))
        prov['reproduction'] = {k: v for k, v in pr.items()}
        done('prove', reproduced=pr['reproduced'], matched=pr['matched'])
        log(f'proof: reproduced={pr["reproduced"]} matched {pr["matched"]}/{pr["delivered_parts"]} '
            f'max dev {pr["max_deviation"]}')
        if not pr['reproduced']:
            shutil.copy(pref + '.csv.gz', os.path.join(conv_out, 'reproduction.csv.gz'))
            raise StageError('ifc_not_reproduced', 'IFC does not reproduce the shipped STEP instance for instance: %d only '
                             'in STEP, %d only in IFC, %d failing, %d name mismatches' % (
                                 pr['n_only_in_step'], pr['n_only_in_ifc'], pr['n_failing'], pr['n_name_mismatch']))
        # ---------------------------------------------------------------- facts for the issue maker
        step('facts')
        import facts_build
        facts = facts_build.build(base, mid, st['sha256'], pin=prov['converter'], partial=job.get('partial'))
        with open(os.path.join(out, 'sds2_facts.json'), 'w') as f:
            json.dump(facts, f, separators=(',', ':'))
        done('facts', counts=facts['counts'], errors=len(facts['errors']))
        if facts['errors']:
            log('facts errors: ' + ' | '.join(e[:300] for e in facts['errors']))
        # ---------------------------------------------------------------- outputs
        shutil.copy(ifc, os.path.join(out, 'model.ifc'))
        shutil.copy(pref + '.csv.gz', os.path.join(out, 'reproduction.csv.gz'))
        prov['ifc'] = dict(file='model.ifc', sha256=isha, bytes=os.path.getsize(ifc), schema='IFC4',
                           originating_system='%s %s / sds2-step-pipeline %s %s %s' % (
                               EMITTER[0], EMITTER[1], pinned['label'], pinned['zip'], pinned['sha256']),
                           deterministic='fixed header time stamp; GlobalIds = sds2label.guid(sha256 of the shipped STEP, '
                                         'instance label); same converter output -> same bytes')
        prov['facts'] = dict(file='sds2_facts.json', sha256=sha256_file(os.path.join(out, 'sds2_facts.json')),
                             counts=facts['counts'])
        rec.update(ok=True, verdict='reproduced', ifc='model.ifc', sha256=isha, facts='sds2_facts.json',
                   facts_sha256=prov['facts']['sha256'],
                   reproduction_sha256=sha256_file(os.path.join(out, 'reproduction.csv.gz')), counts=facts['counts'])
    except StageError as e:
        rec.update(ok=False, verdict=e.verdict, error=str(e))
        log(f'FAILED {e.verdict}: {e}')
    except Exception as e:
        rec.update(ok=False, verdict='error', error=f'{type(e).__name__}: {e}')
        log('EXCEPTION ' + traceback.format_exc())
    for k, v in steps.items():
        v.pop('t0', None)
    prov['ok'] = rec['ok']
    prov['verdict'] = rec['verdict']
    prov['error'] = rec['error']
    prov['steps'] = steps
    prov['environment'] = _environment()
    prov['seconds'] = round(time.time() - t_start, 1)
    with open(os.path.join(out, 'provenance.json'), 'w') as f:
        json.dump(prov, f, indent=1, default=str)
    rec['provenance'] = {k: prov.get(k) for k in ('converter', 'converter_rerun', 'emitter', 'ifc', 'verdict')}
    rec['reproduction'] = {k: (prov.get('reproduction') or {}).get(k) for k in (
        'reproduced', 'delivered_parts', 'ifc_products_with_geometry', 'matched', 'n_only_in_step', 'n_only_in_ifc',
        'n_failing', 'n_name_mismatch', 'max_deviation')}
    rec['steps'] = steps
    rec['seconds'] = prov['seconds']
    rec['files'] = sorted(os.path.relpath(os.path.join(dp, fn), out) for dp, _, fns in os.walk(out) for fn in fns)
    return rec


def _environment():
    env = dict(platform=platform.platform(), python=sys.version.split()[0], conv_python=CONV_PY, pipe_python=PIPE_PY,
               image_id=os.environ.get('MODAL_IMAGE_ID'), task_id=os.environ.get('MODAL_TASK_ID'), nproc=os.cpu_count())
    for k, p in (('conv_freeze', '/opt/conv_freeze.txt'), ('pipe_freeze', '/opt/pipe_freeze.txt')):
        if os.path.exists(p):
            env[k] = [ln.strip() for ln in open(p) if ln.strip()]
    return env
