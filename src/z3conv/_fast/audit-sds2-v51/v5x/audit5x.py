#!/usr/bin/env python3
"""audit-sds2-v5x: regression audit of the SDS2 converter versions v4 -> v5 -> v5.1 -> v5.2 -> v5.3 on the data-3 fleet.
Runs on the agent box over a read-only snapshot made by job.sh (s3/...). Writes out/*.json|csv|txt.

Per job and converter label it merges every piece of evidence:
  outputs   conversions/sds2-step/<id>/[<label>/]job.json + *_stage2_manifest.json + *_stage2.log (+ _not_accepted/) + STEP listing
  result    _state/conv/sds2/results/<id>.json  (stored record = converter.label; alternatives{} = the other side of the last best-of)
  logs      _state/conv/sds2/logs/<host>-<pid>.log  run lines (status reason MB sec id16) + WATCHDOG memory kills, per worker code
  deferred  _state/conv/sds2/deferred/<id>.json (memory-killed, waiting), claims/ (in flight, by code), hosts/ heartbeats (rss now)
Each version's output is re-graded with the deployed index rules (coord build_index.classify_sds2 + rules.json) and with the deployed
worker's best-of estimate (worker.est_class over worker.manifest_summary), both loaded from the deployed source files.
"""
import os, sys, re, json, glob, csv, gzip, ast, collections, statistics, math, time, copy

D = os.path.dirname(os.path.abspath(__file__)); os.chdir(D)
LABELS = ['v4', 'v5', 'v5.1', 'v5.2', 'v5.3', 'v5.4', 'v5.5', 'v5.6', 'v5.7', 'v6']     # labels without evidence are inert
LI = {l: i for i, l in enumerate(LABELS)}
PFX = 'cad-disk-extract/zenitude-data-3/conversions/sds2-step/'
OUT = os.path.join(D, 'out'); os.makedirs(OUT, exist_ok=True)


def lab(code):
    m = re.match(r'z3-sds2-(v[\d.]+?)-20\d\d', str(code or ''))
    return m.group(1) if m else None


def jload(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return None


# ------------------------------------------------------------------ deployed grading code
def worker_funcs():
    src = open('s3/ctl/sds2_worker.py').read()
    t = ast.parse(src)
    ns = {'json': json, 'collections': collections, 're': re, 'os': os}
    for node in t.body:          # every top-level def (definitions only, no side effects): helpers such as holes_summary come along
        if isinstance(node, ast.FunctionDef):
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'deployed_worker.py', 'exec'), ns)
        if isinstance(node, ast.Assign) and any(getattr(x, 'id', None) == 'GRATING' for x in node.targets):
            exec(compile(ast.Module(body=[node], type_ignores=[]), 'deployed_worker.py', 'exec'), ns)
    return ns['manifest_summary'], ns['est_class']


manifest_summary, est_class = worker_funcs()
sys.path.insert(0, os.path.join(D, 's3/ctl'))
import build_index as BI  # noqa: E402
BI.RULES = dict(BI.DEFAULT_RULES); BI.RULES.update(jload('s3/ctl/rules.json') or {})


def index_grade(jid, r):
    """the coordinator's own SDS2 classification of a result-like record -> compact row"""
    try:
        row = BI.classify_sds2({'id': jid, 'action': 'convert'}, copy.deepcopy(r), None)
    except Exception as e:
        return {'class': None, 'error': f'{type(e).__name__}: {e}'}
    return {'class': row.get('class'), 'corpus': row.get('corpus'), 'status': row.get('status'), 'reasons': row.get('reasons'),
            'issues': row.get('issues'), 'standins': [(s.get('type'), s.get('count')) for s in row.get('standins') or []],
            'needs': row.get('needs'), 'solids': row.get('solids'), 'invalid': row.get('invalid_solids'),
            'parts_step': row.get('parts_step'), 'parts_source': row.get('parts_source'),
            'coverage_members': row.get('coverage_members'), 'coverage_connections': row.get('coverage_connections'),
            'weight': (row.get('weight_ratio') or {}).get('steel_ratio_vs_sds2'), 'score': ((row.get('class') or 9),
            len(row.get('issues') or []) + len(row.get('standins') or []) + len(row.get('needs') or []))}


# ------------------------------------------------------------------ snapshot inputs
jobs = {j['id']: j for j in (jload('s3/sds2/jobs.json') or [])}
for j in (jload('s3/sds2/jobs_reconvert.json') or []):
    jobs.setdefault(j['id'], dict(j, reconvert=True))
by16 = collections.defaultdict(list)
for i in jobs:
    by16[i[:16]].append(i)
R = {}
for f in glob.glob('s3/sds2/results/*.json'):
    r = jload(f)
    if r and r.get('id'):
        R[r['id']] = r
for i in R:
    if i[:16] not in by16:
        by16[i[:16]].append(i)
redo = set(jload('s3/sds2/redo.json') or [])
DEF = {}
for f in glob.glob('s3/sds2/deferred/*.json'):
    x = jload(f)
    if x and x.get('id'):
        DEF[x['id']] = x
CLAIMS = {}
for f in glob.glob('s3/sds2/claims/*.json'):
    x = jload(f)
    if x:
        CLAIMS[os.path.basename(f)[:-5]] = x
HOSTS = {}
for f in glob.glob('s3/sds2/hosts/*.json'):
    x = jload(f)
    if x:
        HOSTS[os.path.basename(f)[:-5]] = x
INDEX = {}
try:
    for ln in gzip.open('s3/conv/index.jsonl.gz', 'rt'):
        if ln.strip():
            x = json.loads(ln)
            if x.get('pipeline') == 'sds2':
                INDEX[x['id']] = x
except Exception as e:
    print('index read failed', e)
HIST = jload('s3/conv/history.json') or []
STATUS = jload('s3/conv_status.json') or {}

# STEP listing
STEPS = collections.defaultdict(dict)        # (accepted, id, sub) -> {file: size}
for ln in open('s3/out_listing.txt', errors='replace'):
    p = ln.rstrip('\n').split(None, 3)
    if len(p) < 4 or not p[3].startswith(PFX):
        continue
    rel = p[3][len(PFX):].split('/')
    acc = True
    if rel[0] == '_not_accepted':
        acc = False; rel = rel[1:]
    if len(rel) == 2:
        STEPS[(acc, rel[0], '')][rel[1]] = int(p[2])
    elif len(rel) == 3:
        STEPS[(acc, rel[0], rel[1])][rel[2]] = int(p[2])


# ------------------------------------------------------------------ logs (every worker process)
def tsec(t):
    h, m, s = (int(x) for x in t.split(':'))
    v = h * 3600 + m * 60 + s
    return v + 86400 if h < 12 else v           # fleet started ~20:30Z on 10-01: early-morning times are 10-02


PROC_CODE = {}
for hp, h in HOSTS.items():
    PROC_CODE[hp] = lab(h.get('code'))
KILLRE = re.compile(r'^(\d\d:\d\d:\d\d) WATCHDOG killed (\w+) rss=(\d+)GB(?: need=(\d+)GB)? avail=(\d+)GB(.*)$', re.M)


def kill_rule(suffix):
    s_ = suffix.strip()
    if 'furthest above' in s_:
        return 'v2_over_reservation'
    if 'largest on host' in s_:
        return 'largest_on_host_10pct'
    return 'legacy_own_largest_6pct'


RUNS = collections.defaultdict(list); KILLS = collections.defaultdict(list); PROCS = {}
for f in glob.glob('s3/sds2/logs/*.log'):
    hp = os.path.basename(f)[:-4]
    t = open(f, errors='replace').read()
    m = re.search(r'worker code=(\S+) (\S+) host=', t)
    code = lab(m.group(1)) if m else PROC_CODE.get(hp)
    runtime = m.group(2) if m else (HOSTS.get(hp) or {}).get('runtime')
    PROCS[hp] = {'code': code, 'runtime': runtime, 'lines': t.count('\n') + 1, 'header': bool(m)}
    for mm in KILLRE.finditer(t):
        KILLS[mm.group(2)].append({'code': code, 'runtime': runtime, 't': mm.group(1), 'ts': tsec(mm.group(1)), 'rss_gb': int(mm.group(3)),
                                   'need_gb': int(mm.group(4)) if mm.group(4) else None, 'avail_gb': int(mm.group(5)),
                                   'rule': kill_rule(mm.group(6)), 'proc': hp})
    for mm in re.finditer(r'^(\d\d:\d\d:\d\d)\s+(ok_stage1|ok|fail|deferred)\s+(\S*)\s+(\d+)MB\s+([\d.]+)s\s+(\w+)\s*$', t, re.M):
        RUNS[mm.group(6)].append({'code': code, 't': mm.group(1), 'ts': tsec(mm.group(1)), 'status': mm.group(2),
                                  'reason': mm.group(3) or None, 'mb': int(mm.group(4)), 'sec': float(mm.group(5)), 'proc': hp})


def full_id(i16):
    c = by16.get(i16) or []
    return c[0] if len(c) == 1 else (sorted(c)[0] if c else i16)


RUNS_ID = collections.defaultdict(list); KILLS_ID = collections.defaultdict(list)
for k, v in RUNS.items():
    RUNS_ID[full_id(k)] += v
for k, v in KILLS.items():
    KILLS_ID[full_id(k)] += v


# ------------------------------------------------------------------ per-version output records
def find(d, suffix):
    g = sorted(glob.glob(f'{d}/*{suffix}'))
    return g[0] if g else None


LOGPAT = re.compile(r'(Traceback|Error|error:|exception|Exception|MemoryError|Killed|Segmentation|core dumped|rc=\s*-?\d+|WARNING|warning:)')


def log_digest(p, n=12):
    if not p or not os.path.exists(p):
        return None
    try:
        t = open(p, errors='replace').read()
    except Exception:
        return None
    lines = t.splitlines()
    hits = [l[:220] for l in lines if LOGPAT.search(l)]
    tm = re.findall(r'^.*(?:seconds|wall|elapsed|took).*$', t, re.M)
    return {'bytes': len(t), 'lines': len(lines), 'flag_lines': len(hits), 'flags_head': hits[:n // 2], 'flags_tail': hits[-n // 2:] if len(hits) > n // 2 else [],
            'tail': [l[:220] for l in lines[-6:]], 'timing': [l[:160] for l in tm[-3:]]}


def out_records(jid):
    res = collections.defaultdict(list)
    for acc, base in ((True, f's3/out/{jid}'), (False, f's3/out/_not_accepted/{jid}')):
        for sub in [''] + LABELS[1:]:
            d = base + ('/' + sub if sub else '')
            j = jload(f'{d}/job.json')
            if not j:
                continue
            lb = lab(j.get('code'))
            if lb is None or (sub and lb != sub):
                continue
            man_p = find(d, '_stage2_manifest.json')
            msum = manifest_summary(man_p) if man_p else None
            mraw = jload(man_p) if man_p else None
            files = STEPS.get((acc, jid, sub), {})
            s2 = next((f for f in files if f.endswith('_stage2.step')), None)
            s1 = next((f for f in files if f.endswith('_stage1.step')), None)
            pub = j.get('published')
            if pub is True:
                status, stage = 'ok', 2
            elif pub == 'stage1':
                status, stage = 'ok_stage1', 1
            else:
                status, stage = 'not_accepted', 2
            r = dict(j)
            r['status'] = 'ok' if status == 'not_accepted' else status    # graded as written (not-accepted outputs are graded too)
            if msum:
                r['manifest'] = msum
            key = PFX + (('_not_accepted/' if not acc else '') + jid + ('/' + sub if sub else '') + '/') + ((s2 if stage == 2 else s1) or '')
            r['step'] = {'key': key, 'stage': stage, 'bytes': files.get(s2 if stage == 2 else s1),
                         'solids': ((j.get('validate') or {}).get('solids') if stage == 2 else (j.get('validate1') or {}).get('solids'))}
            if stage == 1 and 'validate1' not in r and isinstance(j.get('stage1'), dict):
                s1d = j['stage1']; r['validate1'] = {'read_status': 'ok', 'solids': s1d.get('solids'), 'valid': s1d.get('valid'),
                                                     'bbox_mm': s1d.get('bbox_mm')}
            ig = index_grade(jid, r)
            v = j.get('validate') or {}; st2 = j.get('stage2') or {}; inv = j.get('inventory') or {}
            m = msum or {}; cnt = m.get('counts') if isinstance(m.get('counts'), dict) else {}
            rb = m.get('readback') if isinstance(m.get('readback'), dict) else {}
            sk = sum(x for x in (m.get('skipped_by_reason') or {}).values() if isinstance(x, (int, float))) if msum else \
                sum(x for x in (inv.get('skipped_by_reason') or {}).values() if isinstance(x, (int, float)))
            w = (m.get('weight') or {}) if msum else {}
            rec = {'label': lb, 'accepted': acc, 'published': pub, 'status': status, 'stage': stage, 'dir': d,
                   'step_file': s2 if stage == 2 else s1, 'step_bytes': files.get(s2 if stage == 2 else s1), 'has_stage2_step': bool(s2),
                   'solids': v.get('solids') if stage == 2 else r['step']['solids'],
                   'invalid': v.get('invalid') if stage == 2 else None,
                   'rb_solids': BI.num(rb.get('solids')) if rb.get('solids') is not None else None,
                   'rb_invalid': (BI.num(rb.get('solids')) - BI.num(rb.get('valid'))) if rb.get('solids') is not None and rb.get('valid') is not None else None,
                   'load_errors': BI.num(rb.get('load_errors')) if rb else None,
                   'skipped': sk, 'skipped_by_reason': (m.get('skipped_by_reason') if msum else inv.get('skipped_by_reason')) or {},
                   'standins_total': (m.get('standins_total') if msum else inv.get('standins_total')),
                   'standins_by_type': (m.get('standins_by_type') if msum else {s['type']: s['count'] for s in inv.get('standins') or []}) or {},
                   'ratio': (w.get('ratio_without_outliers') or w.get('ratio')) if msum else st2.get('steel_ratio'),
                   'ratio_raw': w.get('ratio') if msum else st2.get('steel_ratio'),
                   'm_class': m.get('class'), 'm_corpus': m.get('corpus'), 'm_reasons': m.get('class_reasons'),
                   'counts': {k: (BI.num(x) if not isinstance(x, (int, float)) else x) for k, x in cnt.items()} if cnt else None,
                   'converter_duplicates': m.get('converter_duplicates'),
                   'wall_s': st2.get('wall_s'), 'rc': st2.get('rc'), 'step_mb': st2.get('step_mb'), 'qa': j.get('qa'),
                   'converted': j.get('converted'), 'version': j.get('version'),
                   'est': list(est_class(r)) if status != 'not_accepted' else None, 'index': ig,
                   'log': log_digest(find(d, '_stage2.log')), 'manifest_schema': (mraw or {}).get('schema') if isinstance(mraw, dict) else None,
                   'stage2_reason': j.get('stage2_reason')}
            res[lb].append(rec)
    return res


# ------------------------------------------------------------------ evidence per job
ids = set(R) | {full_id(k) for k in RUNS} | {full_id(k) for k in KILLS} | set(DEF) | set(CLAIMS)
ids |= {os.path.basename(p) for p in glob.glob('s3/out/*') if len(os.path.basename(p)) == 24}
ids |= {os.path.basename(p) for p in glob.glob('s3/out/_not_accepted/*') if len(os.path.basename(p)) == 24}

ORANK = {'ok': 0, 'ok_stage1': 1, 'fail': 2, 'killed': 3}


def outcome_of(ev):
    """best evidence of what a label did on a job -> (outcome, detail)"""
    st = []
    for o in ev['outputs']:
        if o['status'] in ('ok', 'ok_stage1'):
            st.append((o['status'], 'output'))
    if ev['stored']:
        s = ev['stored']['status']; st.append((s if s != 'fail' else 'fail', f"stored:{ev['stored'].get('reason')}"))
    if ev['alt']:
        s = ev['alt'].get('status'); st.append((s if s in ('ok', 'ok_stage1') else 'fail', f"alt:{ev['alt'].get('reason')}"))
    for x in ev['runs']:
        if x['status'] == 'deferred':
            st.append(('killed', 'log:deferred'))
        else:
            st.append((x['status'], f"log:{x['reason']}"))
    if ev['kills'] and not st:
        st.append(('killed', 'log:watchdog'))
    if not st:
        return None, None
    best = min(st, key=lambda s: ORANK.get(s[0], 9))
    fails = sorted({d.split(':', 1)[1] for s, d in st if s == 'fail' and d.split(':', 1)[1] not in ('None', '')})
    return best[0], (best[1] if best[0] != 'fail' else ','.join(fails) or best[1])


rows = []; EV = {}
for jid in sorted(ids):
    r = R.get(jid) or {}; j = jobs.get(jid) or {}
    outs = out_records(jid)
    stored_label = (r.get('converter') or {}).get('label')
    ev = {}
    for lb in LABELS:
        e = {'outputs': outs.get(lb, []), 'stored': None, 'alt': None,
             'runs': [x for x in RUNS_ID.get(jid, []) if x['code'] == lb],
             'kills': [x for x in KILLS_ID.get(jid, []) if x['code'] == lb]}
        if r and stored_label == lb:
            e['stored'] = {k: r.get(k) for k in ('status', 'reason', 'stage2_reason', 'peak_rss_gb', 'sec', 'host', 'finished', 'chosen', 'best_of_note')}
            e['stored']['est'] = list(est_class(r))
            e['stored']['index'] = index_grade(jid, r)
        a = (r.get('alternatives') or {}).get(lb)
        if a:
            e['alt'] = a
        e['outcome'], e['outcome_detail'] = outcome_of(e)
        ev[lb] = e
    # failures of a label known only from the result's own code (no converter label: e.g. out_of_memory after 5 kills)
    if r and not stored_label and lab(r.get('code')) in ev:
        lb = lab(r.get('code'))
        ev[lb]['stored'] = {k: r.get(k) for k in ('status', 'reason', 'kills', 'min_mem_gb', 'sec', 'finished')}
        ev[lb]['outcome'], ev[lb]['outcome_detail'] = outcome_of(ev[lb])
    EV[jid] = ev
    idx = INDEX.get(jid) or {}
    cl = CLAIMS.get(jid) or {}
    row = {'id': jid, 'name': j.get('name') or r.get('name'), 'version': r.get('version') or j.get('version'),
           'model_mb': round((j.get('model_bytes') or r.get('model_bytes') or j.get('size') or 0) / 2 ** 20),
           'code_now': lab(r.get('code')), 'stored_label': stored_label, 'status_now': r.get('status'), 'reason_now': r.get('reason'),
           'chosen': r.get('chosen'), 'best_of_note': r.get('best_of_note'), 'alts': ','.join(sorted(r.get('alternatives') or {})),
           'in_redo': jid in redo, 'deferred_kills': (DEF.get(jid) or {}).get('kills'), 'deferred_min_gb': (DEF.get(jid) or {}).get('min_mem_gb'),
           'claimed_by': lab(cl.get('code')) if cl else None, 'claim_at': cl.get('at'),
           'index_class': idx.get('class'), 'index_corpus': idx.get('corpus'), 'index_status': idx.get('status'),
           'index_converter': idx.get('converter'), 'index_step': idx.get('step_key'), 'peak_rss_gb': r.get('peak_rss_gb')}
    for lb in LABELS:
        e = ev[lb]
        o = next((x for x in e['outputs'] if x['status'] in ('ok', 'ok_stage1')), None) or (e['outputs'][0] if e['outputs'] else None)
        row[f'{lb}_outcome'] = e['outcome']; row[f'{lb}_detail'] = e['outcome_detail']
        row[f'{lb}_kills'] = len(e['kills']); row[f'{lb}_kill_rss_max'] = max([k['rss_gb'] for k in e['kills']] or [0]) or None
        row[f'{lb}_runs'] = len(e['runs'])
        row[f'{lb}_iclass'] = (o or {}).get('index', {}).get('class') if o else None
        row[f'{lb}_mclass'] = (o or {}).get('m_class') if o else None
        row[f'{lb}_solids'] = (o or {}).get('solids') if o else None
        row[f'{lb}_invalid'] = (o or {}).get('invalid') if o else None
        row[f'{lb}_skipped'] = (o or {}).get('skipped') if o else None
        row[f'{lb}_standins'] = (o or {}).get('standins_total') if o else None
        row[f'{lb}_ratio'] = (o or {}).get('ratio') if o else None
        row[f'{lb}_wall_s'] = (o or {}).get('wall_s') if o else None
        row[f'{lb}_est'] = json.dumps((o or {}).get('est')) if o and o.get('est') else None
        row[f'{lb}_stage'] = (o or {}).get('stage') if o else None
    rows.append(row)


# ------------------------------------------------------------------ regressions (every newer label vs every older label with evidence)
def best_out(e):
    return next((x for x in e['outputs'] if x['status'] == 'ok'), None) or next((x for x in e['outputs'] if x['status'] == 'ok_stage1'), None) \
        or next((x for x in e['outputs'] if x['status'] == 'not_accepted'), None)


def dict_diff(a, b):
    a = a or {}; b = b or {}
    out = {}
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if isinstance(x, (int, float)) or isinstance(y, (int, float)):
            if (x or 0) != (y or 0):
                out[k] = [x, y]
    return out


def band(r):
    if r is None:
        return None
    return 0 if 0.95 <= r <= 1.05 else (1 if 0.75 <= r <= 1.3 else 2)


REG = []
for jid, ev in EV.items():
    row = next(x for x in rows if x['id'] == jid)
    for i_new, new in enumerate(LABELS):
        en = ev[new]
        if not en['outcome']:
            continue
        for old in LABELS[:i_new]:
            eo = ev[old]
            if not eo['outcome']:
                continue
            why = []; kind = set()
            ro, rn = ORANK.get(eo['outcome'], 9), ORANK.get(en['outcome'], 9)
            if en['outcome'] == 'killed':
                # newer label has no verdict yet (memory-killed, deferred): only a risk where the older label finished
                if ro <= 1:
                    why.append(f"PENDING {new} memory-killed {len(en['kills'])}x (rss {[k['rss_gb'] for k in en['kills']]} GB, "
                               f"rules {sorted({k['rule'] for k in en['kills']})}) where {old} finished {eo['outcome']}; "
                               f"deferred kills now {(DEF.get(jid) or {}).get('kills')}"); kind.add('pending_oom_risk')
            elif rn > ro:
                why.append(f"outcome {eo['outcome']} -> {en['outcome']} ({en['outcome_detail']})"); kind.add('outcome')
                if 'out_of_memory' in str(en['outcome_detail']):
                    kind.add('oom')
            oo, on = best_out(eo), best_out(en)
            cmp = None
            if oo and on and oo['status'] != 'not_accepted' and on['status'] != 'not_accepted':
                io, inn = oo['index'], on['index']
                if (inn.get('class') or 9) > (io.get('class') or 9):
                    why.append(f"index class {io.get('class')} -> {inn.get('class')}"); kind.add('class')
                mo, mn = oo.get('m_class'), on.get('m_class')
                if mo is not None and mn is not None and {0: 4}.get(mn, mn) > {0: 4}.get(mo, mo):
                    why.append(f"manifest class {mo} -> {mn}"); kind.add('manifest_class')
                if oo['stage'] == on['stage']:
                    so, sn = oo.get('solids'), on.get('solids')
                    if so and sn is not None and sn < 0.99 * so:
                        why.append(f"solids {so} -> {sn}"); kind.add('solids')
                    if (on.get('invalid') or 0) > (oo.get('invalid') or 0):
                        why.append(f"invalid {oo.get('invalid')} -> {on.get('invalid')}"); kind.add('invalid')
                    if (on.get('skipped') or 0) > (oo.get('skipped') or 0):
                        why.append(f"skipped {oo.get('skipped')} -> {on.get('skipped')}"); kind.add('skipped')
                    if (on.get('load_errors') or 0) > (oo.get('load_errors') or 0):
                        why.append(f"load_errors {oo.get('load_errors')} -> {on.get('load_errors')}"); kind.add('load_errors')
                    bo, bn = band(oo.get('ratio')), band(on.get('ratio'))
                    if bo is not None and bn is not None and bn > bo:
                        why.append(f"weight ratio {oo.get('ratio')} -> {on.get('ratio')}"); kind.add('weight')
                    if (on.get('standins_total') or 0) > (oo.get('standins_total') or 0) and LI[old] >= LI['v5.1']:
                        why.append(f"stand-ins {oo.get('standins_total')} -> {on.get('standins_total')}"); kind.add('standins')
                    wo, wn = oo.get('wall_s'), on.get('wall_s')
                    if wo and wn and wn > 2 * wo and wn - wo > 300:
                        why.append(f"converter wall {wo}s -> {wn}s"); kind.add('slower')
                elif on['stage'] > oo['stage']:
                    why.append(f"stage {oo['stage']} -> {on['stage']}"); kind.add('stage')
                cmp = {'old': {k: oo.get(k) for k in ('status', 'stage', 'solids', 'invalid', 'skipped', 'standins_total', 'ratio', 'm_class', 'm_corpus',
                                                      'm_reasons', 'load_errors', 'wall_s', 'step_bytes', 'est', 'qa')},
                       'new': {k: on.get(k) for k in ('status', 'stage', 'solids', 'invalid', 'skipped', 'standins_total', 'ratio', 'm_class', 'm_corpus',
                                                      'm_reasons', 'load_errors', 'wall_s', 'step_bytes', 'est', 'qa')},
                       'index_old': io, 'index_new': inn,
                       'skipped_diff': dict_diff(oo.get('skipped_by_reason'), on.get('skipped_by_reason')),
                       'standins_diff': dict_diff(oo.get('standins_by_type'), on.get('standins_by_type')),
                       'counts_diff': dict_diff(oo.get('counts'), on.get('counts')),
                       'log_new': on.get('log'), 'log_old': (oo.get('log') or {}).get('tail')}
            if en['kills'] and ro <= 1 and rn <= 1 and len(en['kills']) > len(eo['kills']):
                kind.add('oom_info')
            if why:
                REG.append({'id': jid, 'name': row['name'], 'version': row['version'], 'model_mb': row['model_mb'], 'old': old, 'new': new,
                            'kinds': sorted(kind), 'why': why, 'stored_label': row['stored_label'], 'code_now': row['code_now'],
                            'chosen': row['chosen'], 'index_class': row['index_class'],
                            'old_outcome': [eo['outcome'], eo['outcome_detail']], 'new_outcome': [en['outcome'], en['outcome_detail']],
                            'kills_new': en['kills'], 'kills_old': eo['kills'], 'runs_new': en['runs'][-4:], 'runs_old': eo['runs'][-4:],
                            'stored_new': en['stored'], 'stored_old': eo['stored'], 'alt_new': en['alt'], 'alt_old': eo['alt'], 'cmp': cmp,
                            'deferred': DEF.get(jid), 'claim': CLAIMS.get(jid)})


# ------------------------------------------------------------------ best-of check
BEST = []
for jid, ev in EV.items():
    r = R.get(jid)
    if not r:
        continue
    cands = []
    for lb in LABELS:
        for o in ev[lb]['outputs']:
            if o['status'] in ('ok', 'ok_stage1') and o['accepted']:
                cands.append((lb, o))
    if len(cands) < 2 and not r.get('alternatives'):
        continue
    stored = (r.get('converter') or {}).get('label')
    sk = (r.get('step') or {}).get('key') or ''
    ig_stored = index_grade(jid, r) if r.get('status') in ('ok', 'ok_stage1') else None
    ent = {'id': jid, 'name': r.get('name'), 'code_now': lab(r.get('code')), 'stored_label': stored, 'chosen': r.get('chosen'),
           'note': r.get('best_of_note'), 'step_key': sk, 'status': r.get('status'), 'stored_index': ig_stored,
           'stored_est': list(est_class(r)), 'alternatives': r.get('alternatives'), 'index_row_class': (INDEX.get(jid) or {}).get('class'),
           'index_row_converter': (INDEX.get(jid) or {}).get('converter'),
           'versions': {lb: {'index_class': o['index'].get('class'), 'score': o['index'].get('score'), 'est': o['est'], 'solids': o['solids'],
                             'invalid': o['invalid'], 'skipped': o['skipped'], 'standins': o['standins_total'], 'ratio': o['ratio'],
                             'm_class': o['m_class'], 'stage': o['stage'], 'issues': o['index'].get('issues'), 'reasons': o['index'].get('reasons'),
                             'standin_types': o['index'].get('standins')} for lb, o in cands}}
    flags = []
    if cands:
        best_lb, best_o = min(cands, key=lambda c: (tuple(c[1]['index'].get('score') or (9, 99)), -LI[c[0]]))
        ent['best_by_index'] = best_lb
        st_score = tuple((ig_stored or {}).get('score') or (9, 99))
        if stored and stored != best_lb and st_score[0] > (best_o['index'].get('score') or (9,))[0]:
            flags.append(f'kept {stored} (index class {st_score[0]}) but {best_lb} has index class {best_o["index"]["class"]}')
        elif stored and stored != best_lb and st_score > tuple(best_o['index'].get('score') or (9, 99)):
            flags.append(f'kept {stored} (index score {list(st_score)}) but {best_lb} scores {best_o["index"]["score"]}')
        # step key must belong to the stored label
        exp = f'/{jid}/' if stored == 'v4' else f'/{jid}/{stored}/'
        if sk and exp not in sk:
            flags.append(f'step key {sk} does not belong to stored label {stored}')
        # tie decided by noise
        note = r.get('best_of_note') or ''
        m = re.search(r'\(\[(.*?)\] vs \[(.*?)\]\)', note)
        if m:
            x = [float(t) for t in m.group(1).split(',')]; y = [float(t) for t in m.group(2).split(',')]
            if x[:3] == y[:3] and abs(x[3] - y[3]) < 0.005:
                flags.append(f'decided by |ratio-1| difference {abs(x[3] - y[3]):.4f} only (weight noise): older {stored} kept, newer output untagged/unfixed lost')
        # better output orphaned: an accepted output of another label grades better than the stored one
        for lb, o in cands:
            if lb != stored and (o['index'].get('class') or 9) < (st_score[0] if ig_stored else 9):
                flags.append(f'orphaned better output {lb} (class {o["index"].get("class")}) not referenced by the result')
    # alternatives consistency: est recorded in the result vs recomputed from that label's output
    for lb, a in (r.get('alternatives') or {}).items():
        o = best_out(ev[lb]) if lb in ev else None
        if a.get('est') and o and o.get('est') and [round(v, 6) for v in a['est']] != [round(v, 6) for v in o['est']]:
            flags.append(f'alternatives[{lb}].est {a["est"]} != recomputed {o["est"]}')
        if a.get('status') in ('ok', 'ok_stage1') and not any(o_['status'] in ('ok', 'ok_stage1') for o_ in ev.get(lb, {}).get('outputs', [])):
            flags.append(f'alternatives[{lb}] says {a.get("status")} but no accepted {lb} output exists')
    ent['flags'] = sorted(set(flags))
    BEST.append(ent)


# ------------------------------------------------------------------ memory kills by code
def bucket(g):
    return '<1' if g < 1 else ('1-8' if g < 8 else ('8-32' if g < 32 else '>=32'))


OOM = {}
for lb in LABELS + [None]:
    kk = [k for v in KILLS_ID.values() for k in v if k['code'] == lb]
    rr = [x for v in RUNS_ID.values() for x in v if x['code'] == lb]
    OOM[str(lb)] = {'kills': len(kk), 'jobs_killed': len({jid for jid, v in KILLS_ID.items() for k in v if k['code'] == lb}),
                    'kill_rss_gb': dict(collections.Counter(bucket(k['rss_gb']) for k in kk)),
                    'kill_rss_median': statistics.median([k['rss_gb'] for k in kk]) if kk else None,
                    'avail_at_kill_median': statistics.median([k['avail_gb'] for k in kk]) if kk else None,
                    'runs': len(rr), 'by_status': dict(collections.Counter(x['status'] for x in rr)),
                    'fail_reasons': dict(collections.Counter(x['reason'] for x in rr if x['status'] == 'fail').most_common()),
                    'ok_sec_median': statistics.median([x['sec'] for x in rr if x['status'] in ('ok', 'ok_stage1')] or [0]) or None,
                    'processes': sum(1 for p in PROCS.values() if p['code'] == lb)}
oom_fail = [{'id': jid, 'name': (R.get(jid) or {}).get('name') or (jobs.get(jid) or {}).get('name'), 'code': lab((R.get(jid) or {}).get('code')),
             'kills': (R.get(jid) or {}).get('kills'), 'min_mem_gb': (R.get(jid) or {}).get('min_mem_gb'),
             'model_mb': round(((jobs.get(jid) or {}).get('model_bytes') or 0) / 2 ** 20),
             'kill_log': [(k['code'], k['t'], k['rss_gb'], k['avail_gb'], k['proc'].split('.')[0]) for k in sorted(KILLS_ID.get(jid, []), key=lambda k: k['ts'])],
             'other_labels': {lb: EV[jid][lb]['outcome'] for lb in LABELS if EV[jid][lb]['outcome']}}
            for jid in R if (R[jid].get('reason') == 'out_of_memory')]
# kills by (code, watchdog rule)
BYRULE = {}
for v in KILLS_ID.values():
    for k in v:
        e = BYRULE.setdefault(f"{k['code']}|{k.get('runtime')}|{k['rule']}", {'kills': 0, 'rss_lt1': 0, 'rss_1_8': 0, 'rss_ge8': 0, 'avail': [], 'jobs': set(),
                                                                          'first': k['t'], 'last': k['t']})
        e['first'] = min(e['first'], k['t'], key=tsec); e['last'] = max(e['last'], k['t'], key=tsec)
        e['kills'] += 1; e['jobs'].add(k['proc'] and k['t'])
        e['rss_lt1' if k['rss_gb'] < 1 else ('rss_1_8' if k['rss_gb'] < 8 else 'rss_ge8')] += 1; e['avail'].append(k['avail_gb'])
for kk_, e in BYRULE.items():
    e['avail_median'] = statistics.median(e.pop('avail')); e.pop('jobs')
# jobs with a finished (ok / ok_stage1) result that are memory-killed again under newer code: 5 kills in total (kills accumulate
# across converter versions; deferred records are never cleared) finalize them as fail/out_of_memory OVER the good result
AT_RISK = []
for jid, d in DEF.items():
    r = R.get(jid) or {}
    if r.get('status') not in ('ok', 'ok_stage1'):
        continue
    kk = sorted(KILLS_ID.get(jid, []), key=lambda k: k['ts'])
    after = [k for k in kk if (r.get('finished') or '')[11:19] and k['ts'] > tsec((r.get('finished') or '')[11:19])]
    AT_RISK.append({'id': jid, 'name': r.get('name'), 'model_mb': round((r.get('model_bytes') or 0) / 2 ** 20), 'stored_label': (r.get('converter') or {}).get('label'),
                    'status': r.get('status'), 'index_class': (INDEX.get(jid) or {}).get('class'), 'result_finished': r.get('finished'),
                    'peak_rss_gb_of_stored_run': r.get('peak_rss_gb'), 'deferred_kills': d.get('kills'), 'deferred_at': d.get('at'),
                    'deferred_min_mem_gb': d.get('min_mem_gb'), 'kills_after_result': [(k['code'], k['t'], k['rss_gb'], k['rule']) for k in after],
                    'in_redo': jid in redo, 'claimed_by': lab((CLAIMS.get(jid) or {}).get('code')),
                    'kills_to_out_of_memory': max(0, 5 - (d.get('kills') or 0))})
AT_RISK.sort(key=lambda x: (x['kills_to_out_of_memory'], x['id']))
# deferred now: kills by code of the latest kill
dnow = collections.Counter()
for jid, d in DEF.items():
    kk = sorted(KILLS_ID.get(jid, []), key=lambda k: k['ts'])
    dnow[(kk[-1]['code'] if kk else 'no_kill_line', d.get('kills'))] += 1
# running now (heartbeats < 10 min old): rss by code
run_now = collections.defaultdict(list)
for hp, h in HOSTS.items():
    for x in h.get('running') or []:
        run_now[lab(h.get('code'))].append((x.get('rss') or 0) / 2 ** 30)
OOMX = {'by_code': OOM, 'out_of_memory_failures': oom_fail, 'deferred_now_by_last_kill_code_and_kills': {f'{a}|{b}': n for (a, b), n in sorted(dnow.items(), key=str)},
        'running_now_by_code': {str(k): {'n': len(v), 'rss_gb_median': round(statistics.median(v), 1) if v else None, 'rss_gb_max': round(max(v), 1) if v else None}
                                for k, v in run_now.items()},
        'claims_by_code': dict(collections.Counter(lab(c.get('code')) for c in CLAIMS.values())),
        'by_code_rule': BYRULE, 'at_risk_finished_jobs_being_killed': AT_RISK,
        'processes_by_code_runtime': dict(collections.Counter(f"{p['code']}|{p['runtime']}" for p in PROCS.values())),
        'low_rss_kills': [{'id': full_id(i16), 'code': k['code'], 't': k['t'], 'rss_gb': k['rss_gb'], 'avail_gb': k['avail_gb'], 'rule': k['rule'], 'proc': k['proc']}
                          for i16, v in KILLS.items() for k in v if k['rss_gb'] < 1]}

# ------------------------------------------------------------------ repair plan (for fixes/repair_state.py; dry-run there by default)
KILL_MIN_GB = 4
REOPEN_MAX_GB = 8          # all 5 kills below this (reservations of the killed jobs were 17-22 GB): false verdict
PLAN = []
for x in oom_fail:
    jid = x['id']; rss = [k[2] for k in x['kill_log']]
    accepted = [(lb, o) for lb in LABELS for o in EV[jid][lb]['outputs'] if o['accepted'] and o['status'] in ('ok', 'ok_stage1')]
    if accepted:
        lb, o = min(accepted, key=lambda c: (tuple(c[1]['index'].get('score') or (9, 99)), -LI[c[0]]))
        PLAN.append({'id': jid, 'name': x['name'], 'action': 'restore', 'label': lb, 'index_class_of_output': o['index'].get('class'), 'kill_rss_gb': rss})
    elif rss and max(rss) < REOPEN_MAX_GB and len(rss) >= (x.get('kills') or 5):
        PLAN.append({'id': jid, 'name': x['name'], 'action': 'reopen', 'kill_rss_gb': rss, 'kill_rules': sorted({k[0] for k in x['kill_log']})})
for b_ in BEST:
    if any(f.startswith('decided by |ratio-1|') for f in b_['flags']):
        newer = max((lb for lb in b_['versions'] if LI[lb] > LI[b_['stored_label']] and b_['versions'][lb]['index_class'] == (b_['stored_index'] or {}).get('class')),
                    key=lambda lb: LI[lb], default=None)
        if newer:
            PLAN.append({'id': b_['id'], 'name': b_['name'], 'action': 'prefer', 'label': newer, 'from': b_['stored_label']})
for x in AT_RISK:
    kk = sorted(KILLS_ID.get(x['id'], []), key=lambda k: k['ts'])
    rss = [k['rss_gb'] for k in kk]
    if rss and max(rss) < KILL_MIN_GB and len(rss) >= (x['deferred_kills'] or 0):
        PLAN.append({'id': x['id'], 'name': x['name'], 'action': 'reset', 'kill_rss_gb': rss, 'deferred_kills': x['deferred_kills']})
# unfinished jobs heading for a false out_of_memory verdict: >= 2 kills so far, every kill below KILL_MIN_GB, complete kill evidence
done_reset = {p_['id'] for p_ in PLAN}
for jid, d in DEF.items():
    r = R.get(jid) or {}
    if jid in done_reset or r.get('status') in ('ok', 'ok_stage1', 'fail') or (d.get('kills') or 0) < 2:
        continue
    kk = sorted(KILLS_ID.get(jid, []), key=lambda k: k['ts']); rss = [k['rss_gb'] for k in kk]
    if rss and max(rss) < KILL_MIN_GB and len(rss) >= (d.get('kills') or 0):
        PLAN.append({'id': jid, 'name': (jobs.get(jid) or {}).get('name'), 'action': 'reset', 'kill_rss_gb': rss, 'deferred_kills': d.get('kills'), 'unfinished': True})
json.dump(PLAN, open(f'{OUT}/repair_plan.json', 'w'), indent=1)

# ------------------------------------------------------------------ write
summ = {'snapshot': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'conv_status_updated': STATUS.get('updated'),
        'converter_now': (STATUS.get('converters') or {}).get('sds2'), 'results': len(R), 'jobs_listed': len(jobs), 'jobs_audited': len(rows),
        'jobs_with_outputs_of_n_labels': dict(collections.Counter(sum(1 for lb in LABELS if EV[j][lb]['outputs']) for j in EV)),
        'jobs_with_outcomes_of_n_labels': dict(collections.Counter(sum(1 for lb in LABELS if EV[j][lb]['outcome']) for j in EV)),
        'stored_by_code_label_status': {f'{a}|{b}|{c}': n for (a, b, c), n in sorted(collections.Counter(
            (lab(r.get('code')), (r.get('converter') or {}).get('label'), r.get('status')) for r in R.values()).items(), key=str)},
        'regression_pairs': len(REG), 'regression_jobs': len({x['id'] for x in REG}),
        'regression_kinds': dict(collections.Counter(k for x in REG for k in x['kinds'])),
        'final_regression_jobs': sorted({x['id'] for x in REG if set(x['kinds']) - {'pending_oom_risk', 'oom_info'}}),
        'pending_risk_jobs': sorted({x['id'] for x in REG if 'pending_oom_risk' in x['kinds']}),
        'at_risk_finished_jobs': len(AT_RISK), 'at_risk_1_kill_left': sum(1 for x in AT_RISK if x['kills_to_out_of_memory'] <= 1),
        'kills_by_code_rule': {k: {kk: v for kk, v in e.items()} for k, e in BYRULE.items()},
        'regression_pairs_by_new_old': dict(collections.Counter(f"{x['old']}->{x['new']}" for x in REG)),
        'bestof_entries': len(BEST), 'bestof_flagged': sum(1 for b in BEST if b['flags']),
        'repair_plan': dict(collections.Counter(p_['action'] for p_ in PLAN)),
        'index_rows_sds2': len(INDEX), 'logs': len(PROCS), 'logs_without_header': sum(1 for p in PROCS.values() if not p['header']),
        'deferred_now': len(DEF), 'claims_now': len(CLAIMS)}
json.dump(summ, open(f'{OUT}/summary.json', 'w'), indent=1, default=str)
json.dump(REG, open(f'{OUT}/regressions.json', 'w'), indent=1, default=str)
json.dump(BEST, open(f'{OUT}/bestof.json', 'w'), indent=1, default=str)
json.dump(OOMX, open(f'{OUT}/oom.json', 'w'), indent=1, default=str)
json.dump({j: {lb: {'outcome': e['outcome'], 'detail': e['outcome_detail'], 'outputs': e['outputs'], 'stored': e['stored'], 'alt': e['alt'],
                    'runs': e['runs'], 'kills': e['kills']} for lb, e in ev.items() if e['outcome'] or e['outputs']} for j, ev in EV.items()},
          open(f'{OUT}/evidence.json', 'w'), default=str)
keys = list(rows[0].keys()) if rows else []
with open(f'{OUT}/per_job.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, keys); w.writeheader(); [w.writerow(x) for x in rows]
print(json.dumps(summ, indent=1, default=str))
print(json.dumps(OOM, indent=1, default=str))
