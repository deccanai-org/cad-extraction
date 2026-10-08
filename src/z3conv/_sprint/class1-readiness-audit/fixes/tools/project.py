"""project.py TAG BI_MODULE OUT_JSON : projected DB1 class per model when the decoder stage is replaced by an audit decode run (TAG = k / k2)
and the index is built by BI_MODULE (build_index.coord.orig | build_index.c1). STEP-stage signals (read-back, volumes, solids, v6 tags,
join coverage) are carried over from the model's current result; the approx-named product count is recomputed from the decode (bolt groups
with [approx: ...] tags + parts written from an approximate section source). Rows without a current result get a neutral STEP stage
(flag step_stage='not_run_here'). Reads only small JSON from the audit dir (stats / summaries)."""
import os, sys, json, gzip, copy, collections, importlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('INDEX_WORK', '/tmp/c1a_index')
sys.path.insert(0, os.path.join(HERE, 'fixes', 'build_index'))
TAG, BIM, OUTP = sys.argv[1:4]
bi = importlib.import_module(BIM)
bi.RULES = dict(bi.DEFAULT_RULES); bi.RULES.update(json.load(open(os.path.join(HERE, 's3now', 'rules.json'))))   # live coordinator rules
rows = {json.loads(l)['id']: json.loads(l) for l in gzip.open(os.path.join(HERE, 's3now', 'index.jsonl.gz')) if json.loads(l)['pipeline'] == 'db1'}
summ = json.load(open(os.path.join(HERE, TAG, '_summ.json')))
APPROX_HOW = set(bi.DB1_APPROX)
out = {}
for sid, row0 in rows.items():
    sp = os.path.join(HERE, TAG, sid + '.stats.json')
    if not os.path.exists(sp):
        out[sid] = {'projected': None, 'why': 'no audit decode'}; continue
    s = json.load(open(sp))
    rp = os.path.join(HERE, 's3now', 'db1res', sid + '.json')
    r = json.load(open(rp)) if os.path.exists(rp) else None
    if s.get('status') != 'ok':
        out[sid] = {'projected': 3, 'why': f"decode {s.get('status')}", 'error': (s.get('error') or s.get('trace') or '')[-300:]}; continue
    step_stage = 'carried_over'
    if r is None or r.get('status') != 'ok' or not (r.get('validate') or {}).get('read_status'):
        step_stage = 'not_run_here'
        r = {'status': 'ok', 'validate': {'read_status': 'ok', 'solids': 1, 'faces': 1}, 'join': {'coverage': {'all': 1.0}}}
    r2 = copy.deepcopy(r)
    r2.pop('redecode', None); r2.pop('excluded_elements', None); r2.pop('unholed_elements', None)
    r2['convert'] = s['convert']; r2['decoded'] = s.get('decoded') or {}; r2['engine'] = s.get('engine'); r2['code'] = 'audit-' + TAG
    sm = summ.get(sid) or {}
    bs_ = (r2['convert'] or {}).get('bolt_stats')
    if bs_ is not None and sm.get('path') == 'old' and 'bolts_axial_unknown' not in bs_ and sm.get('rows'):
        # final kit (apply_c1_stats): old-path bolts neither axially decoded nor fitted ('axial position as recorded') -> stand-in
        ix = {k: i + 1 for i, k in enumerate(sm['keys'])}
        bs_['bolts_axial_unknown'] = sum(r[0] for r in sm['rows'] if not r[ix['holes_only']] and not r[ix['axial_decoded']] and not r[ix['shifted']])
    dec = r2['decoded']; wbs = dec.get('written_by_source') or {}
    n_ap = (sm.get('group_counts') or {}).get('groups_tagged', 0) + sum(n for h, n in wbs.items() if h in APPROX_HOW)
    v = r2.setdefault('validate', {}); v['approx_products'] = n_ap
    if (r2.get('step') or {}).get('v6'):
        pass
    c = {'id': sid, 'sha256': sid, 'action': 'convert', 'size': row0.get('size'), 'paths': row0.get('paths')}
    try:
        nr = bi.classify_db1(c, r2, None)
    except Exception as e:
        out[sid] = {'projected': None, 'why': f'classify error {type(e).__name__}: {e}'}; continue
    blk = [x['type'] for x in nr['standins'] if not x.get('tolerated')]
    out[sid] = {'projected': nr['class'], 'current': row0['class'], 'engine': s.get('engine'), 'step_stage': step_stage,
                'standins': {x['type']: x['count'] for x in nr['standins']}, 'issues': nr['issues'], 'needs': nr['needs'], 'reasons': nr['reasons'],
                'coverage': {k: nr.get(k) for k in ('coverage_members', 'coverage_connections', 'coverage_other', 'coverage_all')},
                'approx_products': n_ap, 'group_tags': sm.get('group_tags'), 'group_counts': sm.get('group_counts')}
json.dump(out, open(OUTP, 'w'), indent=1, default=str)
cnt = collections.Counter((v.get('current'), v.get('projected')) for v in out.values())
print(TAG, BIM, 'current->projected', dict(cnt))
