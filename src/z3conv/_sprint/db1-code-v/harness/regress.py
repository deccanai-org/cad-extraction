"""regress.py (from tekla-slots fullconv2; outputs to /opt/db1v/regress/TAG + annotationprod agentjobs/db1-code-v/regress/TAG)
fullconv.py KIT TAG IDS_JSON NPAR : the DB1 worker's full chain for verification (decode -> ifc2step6 -> step_check OCC read-back ->
ifc_census -> grade_join), same commands / arguments as worker.process (no crash-bisect rescue, no upload of the STEP to conversions/).
Uploads <sha>.json (worker-shaped record: convert, decoded, validate, step, census, join) to agentwork/class1-readiness-audit/<TAG>/."""
import json, os, sys, re, zlib, gzip, time, hashlib, subprocess, collections, concurrent.futures as cf, importlib.util
import boto3
KIT = os.path.abspath(sys.argv[1]); TAG = sys.argv[2]; IDS = json.load(open(sys.argv[3])); NPAR = int(sys.argv[4])
B = 'bim-proprietary-data'; OUTB = 'annotationprod'; OUT = f'cad-disk-extract/_control/z3conv/agentjobs/db1-code-v/regress/{TAG}'
HERE = '/opt/db1v'; SRC = os.path.join(HERE, 'src'); WK = os.path.join(HERE, 'wk', TAG); os.makedirs(WK, exist_ok=True); os.makedirs(SRC, exist_ok=True)
LOC = os.path.join(HERE, 'regress', TAG); os.makedirs(LOC, exist_ok=True)
PY84 = '/opt/conv/ifc84/bin/python'; PY = '/opt/conv/env/bin/python'
CONV = os.path.join(KIT, 'ifc2step6.py'); CHECK = os.path.join(KIT, 'step_check.py'); CENSUS = os.path.join(KIT, 'ifc_census.py')
LAY = json.load(open(os.path.join(KIT, 'layouts.json')))
s3 = boto3.client('s3', region_name='ap-south-1')
sys.path.insert(0, KIT)
import grade_join
spec = None


def decoded_summary(pl):
    exp = collections.Counter(); wr = collections.Counter(); sk = collections.defaultdict(collections.Counter)
    how = collections.Counter(); miss_prof = collections.Counter(); nosize = collections.Counter(); noprof = 0
    for seq, prof, cat, stt, hw, guid, nc in pl:
        exp[cat] += 1
        if stt == 'written':
            wr[cat] += 1; how[hw] += 1
        else:
            sk[cat][hw] += 1
            if hw in ('unresolved', 'implausible_profile', 'no_profile', 'writer_skip'): miss_prof[prof or '<none>'] += 1
            elif hw == 'profile_without_size': nosize[prof or '<none>'] += 1
            elif hw == 'no_profile': noprof += 1
    return {'expected': dict(exp), 'written': dict(wr), 'skipped': {k: dict(v) for k, v in sk.items()}, 'written_by_source': dict(how),
            'bolt_groups': sum(v.get('bolt_group_excluded', 0) for v in sk.values()),
            'grating_solid': how.get('parametric_grating', 0), 'stud_shank_only': how.get('parametric_stud_shank', 0),
            'catalog_misses': miss_prof.most_common(30), 'profiles_without_size': nosize.most_common(10), 'records_without_profile': noprof}


def run(cmd, log, timeout, env=None):
    with open(log, 'a') as lf:
        try:
            return subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout, env=env).returncode
        except subprocess.TimeoutExpired:
            return 124


def one(job):
    sha = job['sha256']; t0 = time.time(); key = f'{OUT}/{sha}.json'
    if os.path.exists(os.path.join(LOC, sha + '.json')): return sha, 'cached', 0
    d = os.path.join(WK, sha[:12]); os.makedirs(d, exist_ok=True); log = os.path.join(d, 'log.txt')
    rec = {'id': sha, 'sha256': sha, 'code': 'audit-' + TAG, 'kit': KIT}
    try:
        p = os.path.join(SRC, sha + '.db1')
        if not os.path.exists(p):
            s3.download_file(B, job['input_key'], p + '.part'); os.replace(p + '.part', p)
        raw = open(p, 'rb').read(1 << 16)
        data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
        eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode(); rec['engine'] = eng
        lp = os.path.join(d, 'layout.json'); json.dump((LAY.get(eng) or {}).get('layout'), open(lp, 'w'))
        vp = os.path.join(d, 'variants.json'); json.dump([v['layout'] for v in LAY.values() if v.get('layout')], open(vp, 'w'))
        ifc = os.path.join(d, 'model.ifc'); stp = os.path.join(d, 'model.stp'); stats = os.path.join(d, 'convert.json')
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', V6_FAR_VERIFY='0')
        rc = run([PY84, os.path.join(KIT, 'convert_one.py'), p, ifc, os.path.join(KIT, 'tekla_profiles.json'), lp, stats, vp], log, 7200, env)
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
        if rc == 0 and cs.get('status') == 'deferred_layout':
            rc = run([PY84, os.path.join(KIT, 'convert_one.py'), p, ifc, os.path.join(KIT, 'tekla_profiles.json'), lp, stats, vp], log, 7200,
                     dict(env, DB1_FULL_DISCOVERY='1'))
            cs = json.load(open(stats)) if os.path.exists(stats) else {}
        if os.path.exists(stats + '.parts.json.gz'):
            rec['decoded'] = decoded_summary(json.load(gzip.open(stats + '.parts.json.gz', 'rt')))
        rec['convert'] = {k: v for k, v in cs.items() if k not in ('layout', 'trace')}
        if rc != 0 or cs.get('status') != 'ok':
            rec.update(status='fail', reason=cs.get('status') or 'convert_fail'); raise RuntimeError('decode')
        t = time.time()
        rc = run([PY84, CONV, ifc, stp, '--mode', 'hybrid', '--prec', '2', '--threads', '4'], log, 21600, env)
        rec['step_rc'] = rc; rec['step_sec'] = round(time.time() - t, 1)
        st = json.load(open(stp + '.stats.json')) if os.path.exists(stp + '.stats.json') else {}
        if rc != 0 or not os.path.exists(stp):
            rec.update(status='fail', reason='step_fail'); raise RuntimeError('step')
        chk = stp + '.check.json'; sparts = os.path.join(d, 'step_parts.jsonl.gz')
        rcv = run([PY, CHECK, stp, chk, '--parts', sparts], os.path.join(d, 'val.log'), 4 * 3600, env)
        v = json.load(open(chk)) if rcv == 0 and os.path.exists(chk) else {'error': f'read-back rc {rcv}', 'rc': rcv}
        rec['validate'] = v
        rec['step'] = {'bytes': os.path.getsize(stp), 'parts': st.get('parts'), 'faces': st.get('faces'), 'bbox_mm': st.get('bbox'),
                       'v6': {k: st.get(k) for k in ('levels', 'tags', 'repair', 'exact_parts', 'approx_parts', 'surface_fallback_parts') if st.get(k) is not None} or None}
        cj = os.path.join(d, 'census.json'); cparts = os.path.join(d, 'src_parts.jsonl.gz')
        run([PY, CENSUS, ifc, cj, '--parts', cparts], os.path.join(d, 'census.log'), 7200, env)
        rec['census'] = json.load(open(cj)) if os.path.exists(cj) else {'error': 'census'}
        if os.path.exists(cparts) and os.path.exists(sparts):
            rec['join'] = grade_join.join(grade_join.load(cparts), grade_join.load(sparts))
        rec['status'] = 'ok'
    except Exception as e:
        rec.setdefault('status', 'fail'); rec['error'] = f'{type(e).__name__}: {str(e)[:300]}'
        rec['log_tail'] = open(log, errors='replace').read()[-1500:] if os.path.exists(log) else ''
    rec['sec'] = round(time.time() - t0, 1)
    for f in ('model.stp',):
        try: os.remove(os.path.join(d, f))
        except OSError: pass
    json.dump(rec, open(os.path.join(LOC, sha + '.json'), 'w'), default=str)
    try: s3.put_object(Bucket=OUTB, Key=key, Body=json.dumps(rec, default=str).encode())
    except Exception: pass
    return sha, rec['status'], rec['sec']


with cf.ThreadPoolExecutor(NPAR) as ex:
    for res in ex.map(one, IDS): print(*res, flush=True)
print('DONE', flush=True)
