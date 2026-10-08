"""aud.py KIT TAG IDS_JSON NPAR : decode-only run of a DB1 kit (the worker's convert stage, same CLI / layouts / env) on the box.
Per model uploads <sha>.stats.json (convert stats + decoded_summary), <sha>.dump.json.gz (per-bolt audit dump), <sha>.parts.json.gz
to s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/<TAG>/ . Decoder IFC deleted."""
import json, os, sys, re, zlib, gzip, time, hashlib, subprocess, collections, concurrent.futures as cf
import boto3
KIT = os.path.abspath(sys.argv[1]); TAG = sys.argv[2]; IDS = json.load(open(sys.argv[3])); NPAR = int(sys.argv[4])
B = 'bim-proprietary-data'; OUT = f'cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/{TAG}'
HERE = os.getcwd(); SRC = os.path.join(HERE, 'src'); WK = os.path.join(HERE, 'wk', TAG)
os.makedirs(SRC, exist_ok=True); os.makedirs(WK, exist_ok=True)
PY84 = '/opt/conv/ifc84/bin/python'
LAY = json.load(open(os.path.join(KIT, 'layouts.json')))
APPROVED = {e for e, v in LAY.items() if v.get('approved')}
s3 = boto3.client('s3', region_name='ap-south-1')


def decoded_summary(pl):          # worker.decoded_summary (kit k), verbatim
    exp = collections.Counter(); wr = collections.Counter(); sk = collections.defaultdict(collections.Counter)
    how = collections.Counter(); miss_prof = collections.Counter(); nosize = collections.Counter(); noprof = 0
    for seq, prof, cat, stt, hw, guid, nc in pl:
        exp[cat] += 1
        if stt == 'written':
            wr[cat] += 1; how[hw] += 1
        else:
            sk[cat][hw] += 1
            if hw in ('unresolved', 'implausible_profile', 'no_profile', 'writer_skip'):
                miss_prof[prof or '<none>'] += 1
            elif hw == 'profile_without_size':
                nosize[prof or '<none>'] += 1
            elif hw == 'no_profile':
                noprof += 1
    return {'expected': dict(exp), 'written': dict(wr), 'skipped': {k: dict(v) for k, v in sk.items()}, 'written_by_source': dict(how),
            'bolt_groups': sum(v.get('bolt_group_excluded', 0) for v in sk.values()),
            'grating_solid': how.get('parametric_grating', 0), 'stud_shank_only': how.get('parametric_stud_shank', 0),
            'catalog_misses': miss_prof.most_common(30), 'profiles_without_size': nosize.most_common(10), 'records_without_profile': noprof}


def engine_of(path):
    raw = open(path, 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    m = re.search(rb'(\d+\.\d+)', data[:16])
    return m.group(1).decode() if m else None


def fetch(job):
    sha = job['sha256']; p = os.path.join(SRC, sha + '.db1')
    if not (os.path.exists(p) and os.path.getsize(p) == job.get('size')):
        s3.download_file(B, job['input_key'], p + '.part'); os.replace(p + '.part', p)
    sd = os.path.join(SRC, sha[:12] + '_sib'); os.makedirs(sd, exist_ok=True)
    pre = job['input_key'].rsplit('/', 1)[0] + '/'
    for s in job.get('siblings') or []:
        if s.lower() in ('screwdb.db', 'assdb.db') and not os.path.exists(os.path.join(sd, s.lower())):
            try:
                s3.download_file(B, pre + s, os.path.join(sd, s.lower()))
            except Exception as e:
                open(os.path.join(sd, s.lower() + '.err'), 'w').write(str(e)[:300])
    return p


def one(job):
    sha = job['sha256']; t = time.time()
    key = f'{OUT}/{sha}.stats.json'
    try:
        s3.head_object(Bucket=B, Key=key); return sha, 'cached', 0
    except Exception:
        pass
    d = os.path.join(WK, sha[:12]); os.makedirs(d, exist_ok=True)
    rec = {'sha256': sha, 'tag': TAG}
    try:
        p = fetch(job)
        h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
        if h != sha:
            rec.update(status='sha_mismatch', got=h); raise RuntimeError('sha')
        eng = engine_of(p); rec['engine'] = eng
        if eng not in APPROVED:
            rec.update(status='unapproved_engine'); raise RuntimeError('eng')
        lp = os.path.join(d, 'layout.json'); json.dump(LAY[eng].get('layout'), open(lp, 'w'))
        vp = os.path.join(d, 'variants.json'); json.dump([v['layout'] for v in LAY.values() if v.get('layout')], open(vp, 'w'))
        ifc = os.path.join(d, 'model.ifc'); stp = os.path.join(d, 'convert.json'); dump = os.path.join(d, 'dump.json.gz')
        env = dict(os.environ, DB1_AUDIT_DUMP=dump, PYTHONDONTWRITEBYTECODE='1')
        cmd = [PY84, os.path.join(KIT, 'convert_one.py'), p, ifc, os.path.join(KIT, 'tekla_profiles.json'), lp, stp, vp]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=7200)
        cs = json.load(open(stp)) if os.path.exists(stp) else {}
        if r.returncode == 0 and cs.get('status') == 'deferred_layout':
            rec['full_discovery'] = True
            r = subprocess.run(cmd, env=dict(env, DB1_FULL_DISCOVERY='1'), capture_output=True, text=True, timeout=7200)
            cs = json.load(open(stp)) if os.path.exists(stp) else {}
        rec['rc'] = r.returncode; rec['stderr'] = r.stderr[-1500:]
        rec['convert'] = {k: v for k, v in cs.items() if k not in ('trace',)}
        if cs.get('trace'): rec['trace'] = cs['trace'][-1500:]
        plp = stp + '.parts.json.gz'
        if os.path.exists(plp):
            rec['decoded'] = decoded_summary(json.load(gzip.open(plp, 'rt')))
            s3.upload_file(plp, B, f'{OUT}/{sha}.parts.json.gz')
        if os.path.exists(dump):
            s3.upload_file(dump, B, f'{OUT}/{sha}.dump.json.gz')
        rec['status'] = cs.get('status')
    except subprocess.TimeoutExpired:
        rec['status'] = 'timeout'
    except Exception as e:
        rec.setdefault('status', 'error'); rec['error'] = f'{type(e).__name__}: {str(e)[:300]}'
    rec['sec'] = round(time.time() - t, 1)
    for f in ('model.ifc',):
        try: os.remove(os.path.join(d, f))
        except OSError: pass
    s3.put_object(Bucket=B, Key=key, Body=json.dumps(rec, default=str).encode())
    return sha, rec['status'], rec['sec']


IDS.sort(key=lambda j: (j.get('size') or 0) * (1 if os.environ.get('SMALL_FIRST') else -1))       # big first (longest decode) unless SMALL_FIRST
done = []
with cf.ThreadPoolExecutor(NPAR) as ex:
    for res in ex.map(one, IDS):
        done.append(res); print(*res, flush=True)
        s3.put_object(Bucket=B, Key=f'{OUT}/_progress.json', Body=json.dumps({'done': len(done), 'of': len(IDS), 'last': res}).encode())
s3.put_object(Bucket=B, Key=f'{OUT}/_DONE.json', Body=json.dumps({'done': done}, default=str).encode())
