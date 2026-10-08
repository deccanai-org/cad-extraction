#!/usr/bin/env python3
"""SDS2 pipeline audit (read-only). Runs on BOX-C under /work/agentwork/audit-sds2-pipeline.
Pulls the live SDS2 conversion state (index, scan versions, results, deferred, claims, fleet logs, grade results of reused
STEPs, v5.x manifests + logs, v4 pieces CSVs, data-4 results) and writes aggregate JSON to
s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/out/."""
import os, sys, json, gzip, re, io, csv, time, collections, math, traceback
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor

B = 'bim-proprietary-data'
Z3 = 'cad-disk-extract/zenitude-data-3'
Z4 = 'cad-disk-extract/zentitude-data-4'
ST = f'{Z3}/_state/conv'
OUTP = f'{Z3}/_state/agentwork/audit-sds2-pipeline'
W = '/work/agentwork/audit-sds2-pipeline'
SNAP = os.path.join(W, 'snap')
OUTD = os.path.join(W, 'out')
os.makedirs(SNAP, exist_ok=True); os.makedirs(OUTD, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=32, retries={'max_attempts': 20, 'mode': 'standard'}))
C = collections.Counter
T0 = time.time()


def log(*a):
    msg = time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a)
    print(msg, flush=True)
    with open(os.path.join(W, 'progress.txt'), 'a') as f:
        f.write(msg + '\n')
    try:
        s3.put_object(Bucket=B, Key=f'{OUTP}/progress.txt', Body=open(os.path.join(W, 'progress.txt'), 'rb').read())
    except Exception:
        pass


def lst(prefix, bucket=B):
    out = []; tok = None
    while True:
        kw = dict(Bucket=bucket, Prefix=prefix, MaxKeys=1000)
        if tok:
            kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        out += [(o['Key'], o['Size'], o['LastModified'].isoformat()) for o in r.get('Contents', [])]
        if not r.get('IsTruncated'):
            break
        tok = r['NextContinuationToken']
    return out


def get(key, bucket=B):
    p = os.path.join(SNAP, bucket, key)
    if os.path.exists(p):
        return open(p, 'rb').read()
    try:
        b = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
    except Exception:
        return None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(b)
    return b


def getj(key, bucket=B):
    b = get(key, bucket)
    if b is None:
        return None
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    try:
        return json.loads(b)
    except Exception:
        try:
            return [json.loads(l) for l in b.decode().splitlines() if l.strip()]
        except Exception:
            return None


def pmap(fn, items, n=16):
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(fn, items))


def band(v):
    try:
        f = float(v)
        return f'{int(f)}.{int(round((f - int(f)) * 1000)) // 100}xx'
    except Exception:
        return str(v)


def dump(name, obj):
    p = os.path.join(OUTD, name)
    with open(p, 'w') as f:
        json.dump(obj, f, indent=1, default=str)
    s3.put_object(Bucket=B, Key=f'{OUTP}/out/{name}', Body=open(p, 'rb').read(), ContentType='application/json')


def norm_tag(x):
    t = str(x).split(':')[0].split(' (')[0]
    return re.sub(r'_-?[\d.]+(?=_|$)', '', t)


# ------------------------------------------------------------------ 1. load state
log('start')
index = [r for r in getj(f'{ST}/index.jsonl.gz') if r.get('pipeline') == 'sds2']
VERS = getj(f'{ST}/scan/sds2_versions.json') or {}
jobs = getj(f'{ST}/sds2/jobs.json') or []
jobs_by = {j['id']: j for j in jobs}
contents = getj(f'{ST}/scan/contents_sds2.jsonl.gz') or []
cont_by = {c['id']: c for c in contents} if isinstance(contents, list) else {}
recon = getj(f'{ST}/sds2/jobs_reconvert.json') or []
redo = getj(f'{ST}/sds2/redo.json') or []
log('index', len(index), 'versions', len(VERS), 'jobs', len(jobs), 'contents', len(cont_by), 'reconvert', len(recon), 'redo', len(redo))

lists = {}
for sub in ('results', 'deferred', 'claims', 'logs', 'detail', 'retry'):
    lists[sub] = lst(f'{ST}/sds2/{sub}/')
    log('listed', sub, len(lists[sub]), 'bytes', sum(x[1] for x in lists[sub]))
grade_keys = lst(f'{ST}/grade/results/sds2-')
log('grade sds2', len(grade_keys))

results = {}
def _r(k):
    d = getj(k[0])
    if isinstance(d, dict):
        results[d.get('id') or os.path.basename(k[0])[:-5]] = d
pmap(_r, lists['results'])
deferred = {}
def _d(k):
    d = getj(k[0])
    if isinstance(d, dict):
        deferred[d.get('id') or os.path.basename(k[0])[:-5]] = d
pmap(_d, lists['deferred'])
claims = {}
def _c(k):
    d = getj(k[0])
    if isinstance(d, dict):
        claims[os.path.basename(k[0])[:-5]] = dict(d, _mtime=k[2])
pmap(_c, lists['claims'])
retry = {}
def _rt(k):
    d = getj(k[0])
    if isinstance(d, dict):
        retry[os.path.basename(k[0])[:-5]] = d
pmap(_rt, lists['retry'])
grades = {}
def _g(k):
    d = getj(k[0])
    if isinstance(d, dict):
        grades[os.path.basename(k[0])[5:-5]] = d
pmap(_g, grade_keys)
log('loaded results', len(results), 'deferred', len(deferred), 'claims', len(claims), 'retry', len(retry), 'grades', len(grades))

# fleet logs (WATCHDOG lines, fail lines)
fleet_logs = {}
small_logs = [k for k in lists['logs'] if k[1] < 200 << 20]
def _l(k):
    b = get(k[0])
    if b is not None:
        fleet_logs[k[0]] = b.decode('utf-8', 'replace')
pmap(_l, small_logs)
log('fleet logs', len(fleet_logs))

# ------------------------------------------------------------------ 2. per-job conversion outputs (all converter labels)
out_files = {}
def _o(jid):
    ks = lst(f'{Z3}/conversions/sds2-step/{jid}/') + lst(f'{Z3}/conversions/sds2-step/_not_accepted/{jid}/')
    out_files[jid] = ks
    for k, sz, _ in ks:
        if k.endswith('_manifest.json') or (k.endswith('.log') and sz < 20 << 20) or k.endswith('/job.json'):
            get(k)
pmap(_o, sorted(results), 16)
log('outputs listed for', len(out_files), 'jobs; files', sum(len(v) for v in out_files.values()))

# v4 pieces CSV of reused STEPs (duplicate analysis)
def pieces_key(step_key):
    return re.sub(r'_stage2\.step$', '_stage2_pieces.csv', step_key or '')
v4_pieces = {}
def _p(row):
    sk = row.get('step_key')
    if not sk or not sk.endswith('_stage2.step'):
        return
    b = get(pieces_key(sk))
    if b is not None:
        v4_pieces[row['id']] = b
pmap(_p, [r for r in index if r.get('reused')], 16)
log('v4 pieces CSVs', len(v4_pieces))

# data-4 results
d4 = {}
def _d4(k):
    d = getj(k[0])
    if isinstance(d, dict):
        d4[os.path.basename(k[0])[:-5]] = d
pmap(_d4, lst(f'{Z4}/_state/conv/sds2/results/'))
log('data-4 results', len(d4))


# ------------------------------------------------------------------ 3. per-job rows
def label_of(res):
    return ((res or {}).get('converter') or {}).get('label') or ('v4' if res else None)


def load_manifest_files(jid):
    out = {}
    for k, sz, _ in out_files.get(jid, []):
        if k.endswith('_manifest.json'):
            lab = k.split('/')[-2]
            out[lab] = getj(k)
    return out


def load_logs(jid):
    out = {}
    for k, sz, _ in out_files.get(jid, []):
        if k.endswith('.log'):
            lab = k.split('/')[-2]
            b = get(k)
            if b is not None:
                out.setdefault(lab, {})[k.split('/')[-1]] = b.decode('utf-8', 'replace')
    return out


rows = []
for r in index:
    jid = r['id']
    v = VERS.get(jid)
    res = results.get(jid); g = grades.get(jid)
    row = {'id': jid, 'version': v if v else 'unknown', 'band': band(v) if v else ('unknown' if v is None else str(v)),
           'reused': r.get('reused'), 'reuse_from': r.get('reuse_from'), 'class': r.get('class'), 'corpus': r.get('corpus'),
           'status': r.get('status'), 'converter': r.get('converter'), 'converter_code': r.get('converter_code'),
           'issues': r.get('issues') or [], 'reasons': r.get('reasons') or [], 'standins': r.get('standins') or [],
           'size': r.get('size'), 'path': (r.get('paths') or [''])[0], 'n_paths': r.get('n_paths'),
           'claimed': jid in claims, 'claim_code': (claims.get(jid) or {}).get('code'), 'deferred': deferred.get(jid),
           'retry': retry.get(jid), 'result': res, 'grade': g, 'in_reconvert': jid in {j['id'] for j in recon} if False else None,
           'parts_source': r.get('parts_source'), 'parts_step': r.get('parts_step'), 'solids': r.get('solids'),
           'coverage_members': r.get('coverage_members'), 'coverage_connections': r.get('coverage_connections'),
           'weight_ratio': (r.get('weight_ratio') or {}).get('steel_ratio_vs_sds2'), 'manifest_class': r.get('manifest_class'),
           'reference_parts': r.get('reference_parts'), 'step_key': r.get('step_key')}
    rows.append(row)
recon_ids = {j['id'] for j in recon}
redo_ids = set(redo)
for row in rows:
    row['in_reconvert'] = row['id'] in recon_ids
    row['in_redo'] = row['id'] in redo_ids
log('rows', len(rows))

# ------------------------------------------------------------------ 4. version matrix
def model_tags(row):
    t = set()
    if row['class'] == 3:
        t |= {'3:' + norm_tag(x) for x in row['reasons']}
    elif row['class'] in (1, 2):
        t |= {f"{row['class']}:" + norm_tag(x) for x in row['issues']}
        t |= {f"{row['class']}:" + s['type'] for s in row['standins']}
    return t


vm = {}
for row in rows:
    for key in (('band', row['band']), ('version', row['version'])):
        e = vm.setdefault(key[0], {}).setdefault(key[1], {'distinct': 0, 'new': 0, 'reused': 0, 'graded': 0, 'class1': 0, 'class2': 0,
                                                            'class3': 0, 'corpus': C(), 'pending_no_claim': 0, 'in_flight_claim': 0,
                                                            'deferred_mem_killed': 0, 'oom_failed': 0, 'status': C(),
                                                            'converter_of_graded': C(), 'tags_models': C(), 'fail_reasons': C(),
                                                            'in_reconvert_or_redo': 0})
        e['distinct'] += 1
        e['reused' if row['reused'] else 'new'] += 1
        e['status'][row['status']] += 1
        if row['class'] in (1, 2, 3):
            e['graded'] += 1; e[f"class{row['class']}"] += 1
            e['corpus'][str(row['corpus'])] += 1
            e['converter_of_graded'][str(row['converter'] or (row['converter_code'] or '')[8:12] or 'fail')] += 1
            for t in model_tags(row):
                e['tags_models'][t] += 1
        else:
            if row['claimed']:
                e['in_flight_claim'] += 1
            else:
                e['pending_no_claim'] += 1
        if row['deferred']:
            e['deferred_mem_killed'] += 1
        res = row['result']
        if res and res.get('status') == 'fail':
            e['fail_reasons'][f"{res.get('reason')}|{label_of(res)}"] += 1
            if res.get('reason') == 'out_of_memory':
                e['oom_failed'] += 1
        if row['in_reconvert'] or row['in_redo']:
            e['in_reconvert_or_redo'] += 1
for k1 in vm:
    for k2, e in vm[k1].items():
        e['top_tags_by_models'] = e['tags_models'].most_common(12)
        e['tags_models'] = dict(e['tags_models'])
dump('version_matrix.json', vm)
log('version matrix done')

# ------------------------------------------------------------------ 5. feature census (per band) from results / grades / manifests
FEAT_KEYS = ['members', 'members_structural', 'members_with_pieces', 'members_without_geometry', 'placed_pieces', 'pieces_written',
             'pieces_exact', 'pieces_approx', 'reference_members', 'reference_placements', 'reference_unlinked_frames', 'reference_parts',
             'reference_open_shells', 'reference_skipped', 'member_envelopes', 'joist_standins', 'bolts_sds2', 'bolts_nominal',
             'solids_written', 'skipped', 'converter_duplicates_skipped']
S2_KEYS = ['exact', 'plate', 'exact_brep', 'profile_fallback', 'plate_fallback', 'special_primitive', 'bolts_sds2', 'bolts_nominal',
           'rolled', 'fastener', 'bolts', 'skipped', 'envelopes', 'joist_envelopes', 'holes', 'solids', 'valid']


def num(x):
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, dict):
        t = x.get('total')
        if isinstance(t, (int, float)):
            return t
        return sum(v for v in x.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
    if isinstance(x, list):
        return len(x)
    return 0


census = {}
per_job_feat = []
for row in rows:
    src = None; s2 = {}; man = {}; inv = {}; lab = None
    if row['class'] in (1, 2) or (row['result'] and row['result'].get('status') in ('ok', 'ok_stage1')):
        if row['result'] and row['result'].get('status') in ('ok', 'ok_stage1') and not row['reused']:
            src = row['result']
        elif row['reused'] and row['grade']:
            src = row['grade']
        elif row['result'] and row['result'].get('status') in ('ok', 'ok_stage1'):
            src = row['result']
    if src is None:
        continue
    s2 = src.get('stage2') or {}; man = src.get('manifest') or {}; inv = src.get('inventory') or {}
    lab = label_of(src) if src is row['result'] else 'v4'
    raw = load_manifest_files(row['id']).get(lab) if src is row['result'] else None
    cnt = (man.get('counts') if isinstance(man.get('counts'), dict) else None) or ((raw or {}).get('counts') or {})
    e = census.setdefault(row['band'], {'jobs': 0, 'jobs_with': C(), 'sum': C(), 'labels': C(), 'families_n': C(), 'families_jobs': C(),
                                        'standin_types_parts': C(), 'standin_types_jobs': C(), 'skipped_reasons_parts': C(),
                                        'skipped_reasons_jobs': C(), 'empty_job_proof': 0, 'seed_jobs': 0, 'stage1_only': 0,
                                        'holes_cut': 0, 'pieces_with_holes': 0, 'holes_approx': 0, 'jobs_with_holes_info': 0,
                                        'weight_ratio': [], 'family_ratio': collections.defaultdict(list)})
    e['jobs'] += 1; e['labels'][lab] += 1
    if src.get('status') == 'ok_stage1' or (src.get('step') or {}).get('stage') == 1:
        e['stage1_only'] += 1
    for k in FEAT_KEYS:
        if k in cnt:
            n_ = num(cnt.get(k)); e['sum'][k] += n_
            if n_:
                e['jobs_with'][k] += 1
    for k in S2_KEYS:
        if k in s2:
            n_ = num(s2.get(k)); e['sum']['s2_' + k] += n_
            if n_:
                e['jobs_with']['s2_' + k] += 1
    sbk = s2.get('solids_by_kind') or {}
    for k, v in sbk.items():
        if isinstance(v, (int, float)):
            e['sum']['kind_' + k] += v
            if v:
                e['jobs_with']['kind_' + k] += 1
    for k, v in (inv.get('pieces_by_kind') or {}).items():
        e['sum']['inv_kind_' + k] += num(v)
        if num(v):
            e['jobs_with']['inv_kind_' + k] += 1
    for k, v in (inv.get('builders') or {}).items():
        e['sum']['builder_' + k] += num(v)
        if num(v):
            e['jobs_with']['builder_' + k] += 1
    wb = (man.get('weight') or {}).get('by_family') or ((raw or {}).get('weight_check') or {}).get('by_family') or {}
    for f, x in wb.items():
        if isinstance(x, dict):
            e['families_n'][f] += num(x.get('n')); e['families_jobs'][f] += 1
            if x.get('ratio') is not None and num(x.get('n')) >= 5:
                e['family_ratio'][f].append(x['ratio'])
    seen = set()
    for s_ in row['standins']:
        e['standin_types_parts'][s_['type']] += num(s_.get('count'))
        seen.add(s_['type'])
    for t in seen:
        e['standin_types_jobs'][t] += 1
    sbr = (man.get('skipped_by_reason') or inv.get('skipped_by_reason') or {})
    for k, v in sbr.items():
        if isinstance(v, (int, float)):
            e['skipped_reasons_parts'][k] += v; e['skipped_reasons_jobs'][k] += 1
    if man.get('empty_job_proof') or (raw or {}).get('empty_job_proof'):
        e['empty_job_proof'] += 1
    if cnt and num(cnt.get('members')) > 0 and num(cnt.get('placed_pieces')) == 0 and not num(cnt.get('reference_members')):
        e['seed_jobs'] += 1
    hl = (raw or {}).get('holes') or {}
    if hl:
        e['jobs_with_holes_info'] += 1
        e['holes_cut'] += num(hl.get('holes')); e['pieces_with_holes'] += num(hl.get('pieces with holes'))
        e['holes_approx'] += num(hl.get('holes (approximate pieces)'))
    wr = row['weight_ratio']
    if isinstance(wr, (int, float)):
        e['weight_ratio'].append(wr)
    per_job_feat.append({'id': row['id'], 'band': row['band'], 'version': row['version'], 'label': lab, 'class': row['class'],
                         'corpus': row['corpus'], 'counts': cnt, 's2': {k: s2.get(k) for k in S2_KEYS + ['solids_by_kind', 'not_built_names']},
                         'inv_members': inv.get('members_in_job'), 'inv_members_with_pieces': inv.get('members_with_pieces'),
                         'holes': hl, 'weight_ratio': wr})


def qs(a):
    a = sorted(a)
    if not a:
        return None
    return {'n': len(a), 'p05': a[int(0.05 * (len(a) - 1))], 'median': a[len(a) // 2], 'p95': a[int(0.95 * (len(a) - 1))],
            'min': a[0], 'max': a[-1], 'outside_0.95_1.05': sum(1 for x in a if not 0.95 <= x <= 1.05)}


for b_, e in census.items():
    e['weight_ratio'] = qs(e['weight_ratio'])
    e['family_ratio'] = {f: qs(v) for f, v in e['family_ratio'].items()}
dump('feature_census.json', census)
with gzip.open(os.path.join(OUTD, 'per_job_features.jsonl.gz'), 'wt') as f:
    for x in per_job_feat:
        f.write(json.dumps(x, default=str) + '\n')
s3.put_object(Bucket=B, Key=f'{OUTP}/out/per_job_features.jsonl.gz', Body=open(os.path.join(OUTD, 'per_job_features.jsonl.gz'), 'rb').read())
log('census done', len(per_job_feat))

# ------------------------------------------------------------------ 6. failures + log signatures
def sig(txt):
    if not txt:
        return None
    lines = [l for l in txt.splitlines() if l.strip()]
    for l in reversed(lines):
        if re.search(r'(Error|Exception|error:|Traceback|Killed|core dumped|Segmentation)', l):
            return re.sub(r'\d+', 'N', l.strip())[:200]
    return re.sub(r'\d+', 'N', lines[-1].strip())[:200] if lines else None


fails = {}
for row in rows:
    res = row['result']
    if not res or res.get('status') != 'fail':
        continue
    key = f"{res.get('reason')}|{label_of(res)}"
    e = fails.setdefault(key, {'n': 0, 'by_band': C(), 'by_version': C(), 'sigs': C(), 'examples': []})
    e['n'] += 1; e['by_band'][row['band']] += 1; e['by_version'][row['version']] += 1
    s_ = sig(res.get('log_tail') or (res.get('stage2') or {}).get('error') or '')
    e['sigs'][s_] += 1
    if len(e['examples']) < 8:
        e['examples'].append({'id': row['id'], 'version': row['version'], 'size': row['size'], 'path': row['path'][-140:],
                              'kills': res.get('kills'), 'peak_rss_gb': res.get('peak_rss_gb'), 'min_mem_gb': res.get('min_mem_gb'),
                              'detail': str(res.get('detail') or '')[:200], 'sig': s_, 'alternatives': res.get('alternatives')})
for k, e in fails.items():
    e['sigs'] = e['sigs'].most_common(10)
dump('failures.json', fails)
log('failures done')

# ------------------------------------------------------------------ 7. OOM / deferral audit
kill_re = re.compile(r'WATCHDOG killed (\w+) rss=(\d+)GB(?: need=(\d+)GB)? avail=(\d+)GB \(([^)]*)\)')
kills = []
for k, txt in fleet_logs.items():
    host = k.split('/')[-1]
    for ln in txt.splitlines():
        m = kill_re.search(ln)
        if m:
            kills.append({'jid16': m.group(1), 'rss_gb': int(m.group(2)), 'need_gb': int(m.group(3)) if m.group(3) else None,
                          'avail_gb': int(m.group(4)), 'rule': m.group(5)[:60], 'log': host, 't': ln[:19]})
kb = C(); kr = C(); kneed = C()
for x in kills:
    kb['<1' if x['rss_gb'] < 1 else ('1-8' if x['rss_gb'] < 8 else ('8-32' if x['rss_gb'] < 32 else '>=32'))] += 1
    kr[x['rule']] += 1
    if x['need_gb'] is not None:
        kneed['rss<need' if x['rss_gb'] < x['need_gb'] else 'rss>=need'] += 1
dfr = list(deferred.values())
oom = {'watchdog_kills_in_fleet_logs': len(kills), 'kills_by_rss_bucket': dict(kb), 'kills_by_rule': dict(kr), 'kills_rss_vs_need': dict(kneed),
       'deferred_records': len(dfr), 'deferred_by_kills': dict(C(d.get('kills') for d in dfr)),
       'deferred_peak_rss_gb_buckets': dict(C('<1' if (d.get('peak_rss_gb') or 0) < 1 else ('1-8' if d['peak_rss_gb'] < 8 else ('8-32' if d['peak_rss_gb'] < 32 else '>=32')) for d in dfr)),
       'deferred_min_mem_gb_buckets': dict(C('<16' if (d.get('min_mem_gb') or 0) < 16 else ('16-64' if d['min_mem_gb'] < 64 else ('64-256' if d['min_mem_gb'] < 256 else '>=256')) for d in dfr)),
       'deferred_with_result_ok': sum(1 for d in dfr if (results.get(d.get('id')) or {}).get('status') in ('ok', 'ok_stage1')),
       'oom_failed': [{'id': r_['id'], 'kills': r_.get('kills'), 'peak_rss_gb': r_.get('peak_rss_gb'), 'min_mem_gb': r_.get('min_mem_gb'),
                       'size': r_.get('size'), 'version': VERS.get(r_['id']), 'code': r_.get('code')}
                      for r_ in results.values() if r_.get('reason') == 'out_of_memory'],
       'deferred_by_band': dict(C(band(VERS.get(d.get('id'))) for d in dfr)),
       'kills_sample': kills[:40]}
dump('oom.json', oom)
log('oom done', len(kills))

# ------------------------------------------------------------------ 8. reference models
ref = {'jobs': 0, 'by_label': C(), 'placements': 0, 'parts': 0, 'open_shells': 0, 'skipped': 0, 'unlinked_frames': 0,
       'jobs_open_shells_gt0': 0, 'jobs_skipped_gt0': 0, 'skip_reasons': C(), 'by_band': C(), 'jobs_list': []}
for x in per_job_feat:
    cnt = x['counts'] or {}
    if num(cnt.get('reference_members')) or num(cnt.get('reference_parts')) or num(cnt.get('reference_unlinked_frames')):
        ref['jobs'] += 1; ref['by_label'][x['label']] += 1; ref['by_band'][x['band']] += 1
        for k, kk in (('placements', 'reference_placements'), ('parts', 'reference_parts'), ('open_shells', 'reference_open_shells'),
                      ('skipped', 'reference_skipped'), ('unlinked_frames', 'reference_unlinked_frames')):
            ref[k] += num(cnt.get(kk))
        ref['jobs_open_shells_gt0'] += 1 if num(cnt.get('reference_open_shells')) else 0
        ref['jobs_skipped_gt0'] += 1 if num(cnt.get('reference_skipped')) else 0
        ref['jobs_list'].append({'id': x['id'], 'label': x['label'], 'version': x['version'], 'class': x['class'],
                                 'placements': cnt.get('reference_placements'), 'parts': cnt.get('reference_parts'),
                                 'open': cnt.get('reference_open_shells'), 'skipped': cnt.get('reference_skipped'),
                                 'unlinked': cnt.get('reference_unlinked_frames'), 'pieces_written': cnt.get('pieces_written')})
for row in rows:
    res = row['result']
    if res and res.get('manifest'):
        for k, v in ((res.get('manifest') or {}).get('skipped_by_reason') or {}).items():
            if k.startswith('reference'):
                ref['skip_reasons'][k] += v if isinstance(v, (int, float)) else 0
dump('reference.json', ref)
log('reference done', ref['jobs'])

# ------------------------------------------------------------------ 9. v4 reused STEPs: duplicates, solids vs parts, class-1 set
dups = []
for jid, b in v4_pieces.items():
    try:
        rd = list(csv.DictReader(io.StringIO(b.decode('utf-8', 'replace'))))
    except Exception:
        continue
    seen = {}; nd = 0; nd_diff_member = 0; kinds = C(); builders = C(); members = set()
    for x in rd:
        kinds[x.get('kind')] += 1; builders[x.get('builder')] += 1; members.add(x.get('member'))
        try:
            k = (x.get('piece'), round(float(x.get('ox')) / 0.1), round(float(x.get('oy')) / 0.1), round(float(x.get('oz')) / 0.1))
        except Exception:
            continue
        if x.get('kind') in ('member', 'concrete'):
            continue
        if k in seen:
            nd += 1
            if seen[k] != x.get('member'):
                nd_diff_member += 1
        else:
            seen[k] = x.get('member')
    rr = next((r for r in rows if r['id'] == jid), None)
    dups.append({'id': jid, 'version': VERS.get(jid), 'class': rr and rr['class'], 'corpus': rr and rr['corpus'],
                 'rows': len(rd), 'dup_same_piece_origin': nd, 'dup_other_member': nd_diff_member, 'kinds': dict(kinds),
                 'builders': dict(builders), 'members': len(members), 'solids': rr and rr['solids'], 'parts_step': rr and rr['parts_step']})
v4s = {'jobs': len(dups), 'jobs_with_dup_other_member': sum(1 for d in dups if d['dup_other_member']),
       'dup_other_member_total': sum(d['dup_other_member'] for d in dups),
       'class1_jobs': sum(1 for d in dups if d['class'] == 1),
       'class1_with_dup_other_member': [d for d in dups if d['class'] == 1 and d['dup_other_member']],
       'class1_all': [d for d in dups if d['class'] == 1],
       'by_class': dict(C(d['class'] for d in dups))}
dump('v4_reused.json', v4s)
log('v4 reused done', len(dups))

# ------------------------------------------------------------------ 10. regressions between converter labels (alternatives)
reg = []
for jid, res in results.items():
    alts = res.get('alternatives') or {}
    for lab, a in alts.items():
        reg.append({'id': jid, 'version': VERS.get(jid), 'chosen': res.get('chosen') or label_of(res), 'current_status': res.get('status'),
                    'current_reason': res.get('reason'), 'current_label': label_of(res), 'alt_label': lab, 'alt_status': (a or {}).get('status'),
                    'alt_reason': (a or {}).get('reason'), 'alt_est': (a or {}).get('est'), 'best_of_note': res.get('best_of_note')})
regs = {'pairs': len(reg), 'by_pair': dict(C(f"{x['alt_label']}:{x['alt_status']} -> {x['current_label']}:{x['current_status']}" for x in reg)),
        'kept_older': [x for x in reg if x['best_of_note']][:50],
        'newer_failed_older_ok': [x for x in reg if x['current_status'] == 'fail' and x['alt_status'] in ('ok', 'ok_stage1')][:80]}
dump('regressions.json', regs)
log('regressions done', len(reg))

# ------------------------------------------------------------------ 11. reconvert coverage of graded class-2/3 rows
cov = {'graded_2_3': 0, 'targeted': 0, 'not_targeted': 0, 'not_targeted_by_tag': C(), 'not_targeted_by_converter': C(),
       'not_targeted_class1_v4': 0, 'class1_by_converter': C()}
for row in rows:
    if row['class'] == 1:
        cov['class1_by_converter'][f"{row['converter']}|{row['reuse_from']}"] += 1
        if row['converter'] == 'v4' and not (row['in_reconvert'] or row['in_redo']):
            cov['not_targeted_class1_v4'] += 1
    if row['class'] in (2, 3):
        cov['graded_2_3'] += 1
        if row['in_reconvert'] or row['in_redo']:
            cov['targeted'] += 1
        else:
            cov['not_targeted'] += 1
            cov['not_targeted_by_converter'][str(row['converter'] or (row['result'] or {}).get('code'))] += 1
            for t in model_tags(row):
                cov['not_targeted_by_tag'][t] += 1
cov['not_targeted_by_tag'] = cov['not_targeted_by_tag'].most_common(40)
dump('reconvert_coverage.json', cov)
log('reconvert coverage done')

# ------------------------------------------------------------------ 12. pending / unknown-version / incomplete jobs
pend = {'pending_total': 0, 'by_band': C(), 'unknown_version_jobs': [], 'incomplete_layout_jobs': [], 'claims_by_code': C(),
        'claims_age_min_buckets': C()}
now = time.time()
for row in rows:
    if row['class'] is None:
        pend['pending_total'] += 1; pend['by_band'][row['band']] += 1
    if row['version'] in ('unknown', 'unreadable', 'error') or row['band'] in ('unknown', 'unreadable', 'error'):
        j = jobs_by.get(row['id']) or {}
        pend['unknown_version_jobs'].append({'id': row['id'], 'v': VERS.get(row['id']), 'class': row['class'], 'status': row['status'],
                                             'reasons': row['reasons'][:2], 'complete_layout': j.get('complete_layout'),
                                             'n_files': j.get('n_files'), 'size': row['size'], 'path': row['path'][-140:],
                                             'result_reason': (row['result'] or {}).get('reason')})
    j = jobs_by.get(row['id']) or {}
    if j and j.get('complete_layout') is False:
        pend['incomplete_layout_jobs'].append({'id': row['id'], 'v': VERS.get(row['id']), 'class': row['class'], 'n_files': j.get('n_files'),
                                               'path': row['path'][-140:], 'n_paths': row['n_paths']})
for jid, c_ in claims.items():
    pend['claims_by_code'][str(c_.get('code'))] += 1
dump('pending.json', pend)
log('pending done')

# ------------------------------------------------------------------ 13. data-4 SDS2 results
d4s = {'results': len(d4), 'by_status_reason': dict(C(f"{x.get('status')}|{x.get('reason')}" for x in d4.values())),
       'by_code': dict(C(str(x.get('code')) for x in d4.values())),
       'by_version_band': dict(C(band((x.get('stage2') or {}).get('version') or x.get('version')) for x in d4.values()))}
dump('data4.json', d4s)

# ------------------------------------------------------------------ 14. manifest/grader disagreements and members-only proof
dis = []
for row in rows:
    mc = row['manifest_class'] or {}
    if mc and (mc.get('class'), mc.get('corpus')) != (row['class'], row['corpus']):
        dis.append({'id': row['id'], 'version': row['version'], 'converter': row['converter'], 'manifest': [mc.get('class'), mc.get('corpus')],
                    'index': [row['class'], row['corpus']], 'mreasons': (mc.get('reasons') or [])[:3], 'issues': row['issues'][:4],
                    'reasons': row['reasons'][:3], 'cm': row['coverage_members'], 'cc': row['coverage_connections']})
dump('manifest_vs_grader.json', {'n': len(dis), 'by_pair': dict(C(f"{d['manifest']}->{d['index']}" for d in dis)), 'rows': dis})

# members-only / envelope jobs: does the job folder hold piece files? (files manifest: subm/<n> count)
def files_of(jid):
    j = jobs_by.get(jid) or cont_by.get(jid) or {}
    fk = j.get('files_key')
    if not fk:
        return None
    d = getj(fk)
    return d if isinstance(d, list) else None


env_rows = [row for row in rows if row['class'] in (2, 3) and any(s['type'] in ('member_as_envelope', 'member_envelope') for s in row['standins'])]
env_rows += [row for row in rows if row['class'] == 3 and any('member_coverage' in x for x in row['reasons'])]
env_out = []
def _env(row):
    fl = files_of(row['id'])
    if fl is None:
        return None
    subm = [f for f in fl if re.match(r'(?i)^subm/\d+$', f['p'].replace('\\', '/'))]
    mem = [f for f in fl if re.match(r'(?i)^mem/\d+$', f['p'].replace('\\', '/'))]
    envn = sum(num(s.get('count')) for s in row['standins'] if s['type'] in ('member_as_envelope', 'member_envelope'))
    return {'id': row['id'], 'version': row['version'], 'class': row['class'], 'corpus': row['corpus'], 'converter': row['converter'],
            'envelopes': envn, 'subm_piece_files': len(subm), 'subm_nonzero': sum(1 for f in subm if f['size'] > 0),
            'mem_files': len(mem), 'parts_step': row['parts_step'], 'cm': row['coverage_members'], 'reasons': row['reasons'][:2]}
env_out = [x for x in pmap(_env, env_rows, 16) if x]
dump('envelope_jobs.json', {'n': len(env_out), 'rows': env_out,
                            'summary': {'jobs_all_envelopes_no_subm': sum(1 for x in env_out if x['subm_piece_files'] == 0),
                                        'jobs_with_envelopes_and_subm_files': sum(1 for x in env_out if x['subm_piece_files'] > 0)}})
log('envelope proof done', len(env_out))

# ------------------------------------------------------------------ 15. all rows (compact) for the Mac
with gzip.open(os.path.join(OUTD, 'rows.jsonl.gz'), 'wt') as f:
    for row in rows:
        res = row['result'] or {}
        f.write(json.dumps({k: row[k] for k in ('id', 'version', 'band', 'reused', 'reuse_from', 'class', 'corpus', 'status', 'converter',
                                                 'converter_code', 'issues', 'reasons', 'size', 'path', 'claimed', 'claim_code', 'in_reconvert',
                                                 'in_redo', 'parts_source', 'parts_step', 'solids', 'coverage_members', 'coverage_connections',
                                                 'weight_ratio', 'manifest_class', 'reference_parts', 'step_key')} |
                           {'standin_types': sorted({s['type'] for s in row['standins']}),
                            'deferred_kills': (row['deferred'] or {}).get('kills'), 'deferred_peak': (row['deferred'] or {}).get('peak_rss_gb'),
                            'res_status': res.get('status'), 'res_reason': res.get('reason'), 'res_label': label_of(res) if res else None,
                            'res_code': res.get('code'), 'res_alts': list((res.get('alternatives') or {}).keys()), 'res_chosen': res.get('chosen'),
                            'peak_rss_gb': res.get('peak_rss_gb'), 'sec': res.get('sec')}, default=str) + '\n')
s3.put_object(Bucket=B, Key=f'{OUTP}/out/rows.jsonl.gz', Body=open(os.path.join(OUTD, 'rows.jsonl.gz'), 'rb').read())
log('DONE', round(time.time() - T0), 's')
s3.put_object(Bucket=B, Key=f'{OUTP}/DONE', Body=b'done')
