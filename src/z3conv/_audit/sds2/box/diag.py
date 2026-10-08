#!/usr/bin/env python3
"""SDS2 audit diagnostics on BOX-C (read-only on state; writes only under agentwork/audit-sds2-pipeline/diag/).
D5 v5.3 re-run of every v4 class-1 job; D1 reference-skip causes (jfkf, v5.3); D2 bolt / hardware overlap probe;
D4 member census (low member coverage + calibration failures); D3 v4 STEP stand-in tags; D6 incomplete job folders."""
import os, sys, json, gzip, re, time, subprocess, collections, shutil, threading, traceback
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor

B = 'bim-proprietary-data'
Z3 = 'cad-disk-extract/zenitude-data-3'
ST = f'{Z3}/_state/conv'
OUTP = f'{Z3}/_state/agentwork/audit-sds2-pipeline/diag'
W = '/work/agentwork/audit-sds2-pipeline'
D = f'{W}/diag'
PY = f'{W}/env/bin/python'
PIPE = f'{W}/v53/sds2-step-pipeline'
os.makedirs(D, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries={'max_attempts': 20, 'mode': 'standard'}))
LOCK = threading.Lock()
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}


def log(*a):
    msg = time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a)
    print(msg, flush=True)
    with LOCK:
        with open(f'{D}/progress.txt', 'a') as f:
            f.write(msg + '\n')
        try:
            s3.put_object(Bucket=B, Key=f'{OUTP}/progress.txt', Body=open(f'{D}/progress.txt', 'rb').read())
        except Exception:
            pass


def getj(key):
    b = s3.get_object(Bucket=B, Key=key)['Body'].read()
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    try:
        return json.loads(b)
    except Exception:
        return [json.loads(l) for l in b.decode().splitlines() if l.strip()]


def put(local, key):
    try:
        s3.upload_file(local, B, f'{OUTP}/{key}')
    except Exception as e:
        log('upload fail', key, e)


def env():
    e = dict(os.environ, PYTHONUNBUFFERED='1', MPLBACKEND='Agg')
    ex = f'{W}/env/lib/libexpat.so.1'
    if os.path.exists(ex):
        e['LD_PRELOAD'] = ex
    return e


index = {r['id']: r for r in getj(f'{ST}/index.jsonl.gz') if r.get('pipeline') == 'sds2'}
contents = {c['id']: c for c in getj(f'{ST}/scan/contents_sds2.jsonl.gz')}
jobs = {j['id']: j for j in getj(f'{ST}/sds2/jobs.json')}
log('loaded', len(index), len(contents), len(jobs))


def files_key(jid):
    return (jobs.get(jid) or {}).get('files_key') or (contents.get(jid) or {}).get('files_key')


def fetch(jid, name):
    fl = getj(files_key(jid))
    dest = f'{D}/jobs/{jid}'
    jd = f'{dest}/{name}'
    items = []
    for f in fl:
        parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
        items.append((f.get('key') or '', os.path.join(jd, *parts), f['size']))
    def one(it):
        k, p, sz = it
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not k:
            open(p, 'wb').close(); return 0
        for att in range(5):
            try:
                if sz < (64 << 20):
                    with open(p, 'wb') as fh:
                        fh.write(s3.get_object(Bucket=B, Key=k)['Body'].read())
                else:
                    s3.download_file(B, k, p)
                return os.path.getsize(p)
            except Exception:
                time.sleep(1 + att)
        return -1
    with ThreadPoolExecutor(32) as ex:
        got = list(ex.map(one, items))
    return jd, {'files': len(items), 'bytes': sum(x for x in got if x > 0), 'errors': sum(1 for x in got if x < 0)}


def run(cmd, logf, timeout):
    t = time.time()
    with open(logf, 'w') as lf:
        try:
            p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env(), timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = 'timeout'
    return rc, round(time.time() - t)


def safe(n):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', n)[:60]


# ------------------------------------------------------------------ D5: v5.3 re-run of the v4 class-1 jobs
def d5_one(jid):
    r = index[jid]
    name = safe(((r.get('paths') or [' :: job'])[0].split(' :: ')[-1].rstrip('/').split('/')[-1]) or 'job') + '_' + jid[:6]
    out = f'{D}/conv/{jid}'; os.makedirs(out, exist_ok=True)
    try:
        jd, fs = fetch(jid, name)
        step = f'{out}/{name}_stage2.step'
        rc, sec = run([PY, '-u', f'{PIPE}/decode/sds2_to_step.py', jd, '-o', step, '--stage', '2', '--verify'], f'{out}/convert.log', 5400)
        if jid in ('ca8aba5e52a716ef8eb11fa8',):
            run([PY, f'{W}/member_census.py', PIPE, jd, f'{out}/member_census.json'], f'{out}/census.log', 1800)
        summ = {'id': jid, 'name': name, 'version': r.get('version'), 'v4_class': r.get('class'), 'v4_corpus': r.get('corpus'),
                'fetch': fs, 'rc': rc, 'sec': sec, 'step_mb': round(os.path.getsize(step) / 2 ** 20, 1) if os.path.exists(step) else None}
        mf = f'{out}/{name}_stage2_manifest.json'
        if os.path.exists(mf):
            m = json.load(open(mf))
            summ.update(manifest_class=m.get('class'), corpus=m.get('corpus'), class_reasons=m.get('class_reasons'), counts=m.get('counts'),
                        standins=(m.get('standins') or {}).get('by_type'), skipped=(m.get('skipped') or {}).get('by_reason') if isinstance(m.get('skipped'), dict) else None,
                        weight=(m.get('weight_check') or {}).get('ratio'), holes=m.get('holes'),
                        readback={k: (m.get('readback') or {}).get(k) for k in ('solids', 'valid', 'invalid', 'load_errors')})
        json.dump(summ, open(f'{out}/summary.json', 'w'), indent=1, default=str)
        for f in os.listdir(out):
            if not f.endswith('.step'):
                put(f'{out}/{f}', f'conv/{jid}/{f}')
        log('D5', jid[:12], name, 'rc', rc, sec, 's', summ.get('manifest_class'), summ.get('corpus'), (summ.get('class_reasons') or [])[:2])
        return summ
    except Exception as e:
        log('D5 error', jid, e, traceback.format_exc()[-300:])
        return {'id': jid, 'error': str(e)}
    finally:
        shutil.rmtree(f'{D}/jobs/{jid}', ignore_errors=True)
        for f in os.listdir(out):
            if f.endswith('.step'):
                os.remove(f'{out}/{f}')


def d5():
    c1 = [i for i, r in index.items() if r.get('class') == 1 and r.get('converter') == 'v4']
    c1.sort(key=lambda i: -(index[i].get('size') or 0))
    log('D5 jobs', len(c1))
    with ThreadPoolExecutor(5) as ex:
        res = list(ex.map(d5_one, c1))
    json.dump(res, open(f'{D}/d5_summary.json', 'w'), indent=1, default=str)
    put(f'{D}/d5_summary.json', 'd5_summary.json')
    log('D5 done')


# ------------------------------------------------------------------ D1/D2/D4: single-job probes
def probe(tag, jid, script, extra_args, need_skipped=None, keep_job=False, timeout=7200):
    r = index.get(jid) or {}
    name = safe(((r.get('paths') or [' :: job'])[0].split(' :: ')[-1].rstrip('/').split('/')[-1]) or 'job') + '_' + jid[:6]
    out = f'{D}/{tag}'; os.makedirs(out, exist_ok=True)
    try:
        jd, fs = fetch(jid, name)
        log(tag, 'fetched', jid[:12], fs)
        args = []
        for a in extra_args:
            args.append(a.replace('{JOB}', jd).replace('{OUT}', out).replace('{NAME}', name))
        if need_skipped:
            sk = f'{out}/skipped.csv'
            s3.download_file(B, need_skipped, sk)
        rc, sec = run([PY, f'{W}/{script}', PIPE, jd] + args, f'{out}/{tag}.log', timeout)
        log(tag, 'rc', rc, sec, 's')
    except Exception as e:
        log(tag, 'error', e, traceback.format_exc()[-300:])
    finally:
        if not keep_job:
            shutil.rmtree(f'{D}/jobs/{jid}', ignore_errors=True)
        for f in os.listdir(out):
            if not f.endswith('.step') and os.path.isfile(f'{out}/{f}'):
                put(f'{out}/{f}', f'{tag}/{f}')


def probes():
    # D1: jfkf (7.331 reference model, v5.3: 624 of 694 placements skipped)
    probe('d1_ref_jfkf', '23c1072354fa68f340d83fcc', 'ref_causes.py', ['{OUT}/skipped.csv', '{OUT}/ref_causes.json'],
          need_skipped=f'{Z3}/conversions/sds2-step/23c1072354fa68f340d83fcc/v5.3/jfkf_23c107_stage2_skipped.csv')
    # D2: Befor North (8.007; 1,104 BLT hardware pieces, 17 SDS2 bolt records, 276 nominal bolts on v5.1)
    probe('d2_bolts_befor_north', '11be36488546683dedb49806', 'bolt_probe.py', ['{OUT}/probe_stage2.step', '{OUT}/bolt_probe.json'])
    # D4: member census - v5.1 class 3 member_coverage 0.12 (twin of the v4 class-1 ca8aba5e) and calibration failures
    for tag, jid in (('d4_census_north_urban_b244541c', 'b244541c34043e8c7783bd42'), ('d4_census_dfgh_7720', '606dfec917f13fbd2c6fd0a5'),
                     ('d4_census_tg_7619', '414b6e937ecb321fe0a584df'), ('d4_census_dfgter_7613', '1c5919db269f6280bb64c56c'),
                     ('d4_census_str_7425', '2ac238d79bebe13754a62292'), ('d4_census_grand_stair_7720', 'ade4790fed14255c6f3dab7a')):
        probe(tag, jid, 'member_census.py', ['{OUT}/member_census.json'], timeout=1800)
    log('probes done')


# ------------------------------------------------------------------ D3: v4 STEP product names (stand-in tags)
def d3():
    cands = [r for r in index.values() if r.get('reused') and r.get('converter') == 'v4' and r.get('class') == 2
             and (r.get('step_bytes') or 0) < 60 << 20 and r.get('step_key')]
    want = {}
    for typ in ('joist_as_envelope_box', 'member_as_envelope', 'nominal_bolt_from_hole_stack', 'concrete_as_prism',
                'profile_fallback_approximate_no_holes', 'grating_as_solid_panel'):
        for r in sorted(cands, key=lambda r: r.get('step_bytes') or 0):
            if any(s['type'] == typ for s in r.get('standins') or []) and r['id'] not in want:
                want[r['id']] = typ
                break
    rx = re.compile(r"=\s*PRODUCT\('([^']*)'")
    out = []
    for jid, typ in want.items():
        r = index[jid]
        p = f'{D}/d3_{jid}.step'
        try:
            s3.download_file(B, r['step_key'], p)
            names = []
            with open(p, encoding='latin-1') as f:
                for ln in f:
                    m = rx.search(ln)
                    if m:
                        names.append(m.group(1))
            c = collections.Counter()
            for n in names:
                low = n.lower()
                c['products'] += 1
                c['approx_tag'] += '[approx' in low
                c['joist'] += 'joist' in low
                c['envelope'] += 'envelope' in low
                c['nominal'] += 'nominal' in low
                c['bolt'] += low.startswith('bolt')
                c['concrete'] += 'conc' in low or 'concrete' in low
                c['grating'] += 'grating' in low or ' gt' in low or '/ gr' in low
            out.append({'id': jid, 'for_standin': typ, 'standins_in_index': [(s['type'], s['count']) for s in r.get('standins') or []][:12],
                        'counts': dict(c), 'sample_names': [n for n in names if any(k in n.lower() for k in ('joist', 'envelope', 'nominal', 'bolt', 'conc'))][:12]})
        except Exception as e:
            out.append({'id': jid, 'error': str(e)})
        finally:
            if os.path.exists(p):
                os.remove(p)
    json.dump(out, open(f'{D}/d3_v4_tags.json', 'w'), indent=1)
    put(f'{D}/d3_v4_tags.json', 'd3_v4_tags.json')
    log('D3 done', len(out))


# ------------------------------------------------------------------ D6: incomplete job folders
def d6():
    res = []
    for jid, r in index.items():
        if not any('source_job_files_missing' in x for x in r.get('reasons') or []):
            continue
        fk = files_key(jid)
        try:
            fl = getj(fk) if fk else []
        except Exception:
            fl = []
        ps = [f['p'].replace('\\', '/').lower() for f in fl]
        top = collections.Counter(p.split('/')[0] for p in ps)
        name = (r.get('paths') or [''])[0].split(' :: ')[-1].rstrip('/').split('/')[-1].lower()
        sib = [c['id'] for c in contents.values() if c['id'] != jid and
               ((c.get('paths') or [''])[0].split(' :: ')[-1].rstrip('/').split('/')[-1].lower() == name)]
        res.append({'id': jid, 'path': (r.get('paths') or [''])[0][-160:], 'n_paths': r.get('n_paths'), 'files': len(ps),
                    'has_main_jsetup': 'main/jsetup' in ps, 'has_main_job_mtrl': 'main/job_mtrl' in ps, 'has_mem_idx': 'mem/mem_idx' in ps,
                    'mem_member_files': sum(1 for p in ps if re.match(r'^mem/\d+$', p)), 'subm_files': sum(1 for p in ps if re.match(r'^subm/\d+$', p)),
                    'top_dirs': dict(top.most_common(8)), 'same_name_other_contents': [(s, (index.get(s) or {}).get('class'), (index.get(s) or {}).get('status')) for s in sib][:8]})
    json.dump(res, open(f'{D}/d6_incomplete.json', 'w'), indent=1)
    put(f'{D}/d6_incomplete.json', 'd6_incomplete.json')
    log('D6 done', len(res))


if __name__ == '__main__':
    what = sys.argv[1:] or ['d6', 'd3', 'probes', 'd5']
    ths = []
    for w in what:
        t = threading.Thread(target=globals()[w]); t.start(); ths.append(t)
        if w in ('d6', 'd3'):
            t.join()
    for t in ths:
        t.join()
    log('ALL DONE')
    s3.put_object(Bucket=B, Key=f'{OUTP}/DONE', Body=b'done')
