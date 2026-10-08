"""grade_full.py DIR BI_MODULE : grade full-chain verification records (real STEP read-back, volumes, join) with the coordinator's
classify_db1 (BI_MODULE) + live rules.json"""
import os, sys, json, glob, importlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('INDEX_WORK', '/tmp/c1a_index'); sys.path.insert(0, os.path.join(HERE, 'fixes', 'build_index'))
bi = importlib.import_module(sys.argv[2]); bi.RULES = dict(bi.DEFAULT_RULES); bi.RULES.update(json.load(open(os.path.join(HERE, 's3now', 'rules.json'))))
out = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], '*.json'))):
    if '_DONE' in f: continue
    r = json.load(open(f)); sid = r['id']
    nr = bi.classify_db1({'id': sid, 'sha256': sid, 'action': 'convert'}, r, None)
    v = r.get('validate') or {}; j = r.get('join') or {}
    out[sid] = {'class': nr['class'], 'standins': {x['type']: x['count'] for x in nr['standins']}, 'issues': nr['issues'], 'needs': nr['needs'],
                'reasons': nr['reasons'], 'coverage_all': nr.get('coverage_all'), 'read_status': v.get('read_status'), 'solids': v.get('solids'),
                'invalid': v.get('invalid_solids_est', v.get('invalid')), 'approx_products': v.get('approx_products'),
                'volume': {k: (j.get('volume') or {}).get(k) for k in ('checked', 'within_5pct', 'outside_5pct', 'outside_curved_gross', 'median')},
                'v6_tags': ((r.get('step') or {}).get('v6') or {}).get('tags'), 'step_sec': r.get('step_sec')}
    print(sid[:12], 'class', nr['class'], out[sid]['standins'], nr['issues'], nr['needs'][:1], 'solids', v.get('solids'), 'invalid', out[sid]['invalid'],
          'approx', v.get('approx_products'), 'vol', out[sid]['volume'], 'v6', out[sid]['v6_tags'])
json.dump(out, open(os.path.join(HERE, os.path.basename(sys.argv[1].rstrip('/')) + '_graded.json'), 'w'), indent=1)
