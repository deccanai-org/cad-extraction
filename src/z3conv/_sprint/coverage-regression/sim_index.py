#!/usr/bin/env python3
"""Offline replay of build_index.classify_db1 + the best-of choice in once() on real inputs (no S3 writes).

usage: sim_index.py BUILD_INDEX.py CONTENTS.jsonl.gz RESULTS_DIR GRADES_DIR [--rules rules.json] [--ids a,b,..] [--json OUT]
  RESULTS_DIR: db1/results/<sha>.json   GRADES_DIR: grade/results/db1-<sha>.json
Prints one line per model: chosen row (class, reasons, coverage, reused?) + the losing alternative.
"""
import sys, os, json, gzip, glob, importlib.util, argparse, tempfile

ap = argparse.ArgumentParser()
ap.add_argument('bi'); ap.add_argument('contents'); ap.add_argument('results'); ap.add_argument('grades')
ap.add_argument('--rules'); ap.add_argument('--ids'); ap.add_argument('--json')
a = ap.parse_args()
os.environ.setdefault('INDEX_WORK', tempfile.mkdtemp(prefix='simidx_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(a.bi)))
spec = importlib.util.spec_from_file_location('bi_sim', a.bi)
bi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bi)          # module import creates a boto3 client object only (no calls)
bi.RULES = dict(bi.DEFAULT_RULES)
if a.rules:
    bi.RULES.update(json.load(open(a.rules)))

contents = [json.loads(l) for l in gzip.open(a.contents, 'rt') if l.strip()]
res = {os.path.basename(p)[:-5]: json.load(open(p)) for p in glob.glob(os.path.join(a.results, '*.json'))}
grades = {os.path.basename(p)[:-5]: json.load(open(p)) for p in glob.glob(os.path.join(a.grades, 'db1-*.json'))}
want = set(x.strip() for x in a.ids.split(',')) if a.ids else None


def score(r):                       # identical to build_index.once().score
    return ((r['class'] or 9), len(r['issues']) + len(r['standins']) + len(r['needs']))


best_of = getattr(bi, 'best_of_db1', None)       # patched module exposes its chooser; stock one uses the inline rule
out = []
for c in contents:
    if want and not any(c['id'].startswith(w) for w in want):
        continue
    g = grades.get(f'db1-{c["id"]}')
    res_ = res.get(c['id'])
    if c['action'] == 'reuse' and res_ is not None:
        rr = bi.classify_db1(c, None, g)
        rn = bi.classify_db1(dict(c, action='convert'), res_, None)
        if rr is None or rn is None:
            r = rr or rn; why = 'one side missing'
        elif best_of is not None:
            r, why = best_of(rr, rn)
        elif rn['class'] is not None and (rr['class'] is None or score(rn) <= score(rr)):
            rn['supersedes'] = {'from': rr.get('reuse_from'), 'step_key': rr.get('step_key'), 'class': rr['class']}
            r = rn; why = f'stock score rn{score(rn)} <= rr{score(rr)}'
        else:
            rr['alternative'] = {'converter_code': rn.get('converter_code'), 'class': rn['class'], 'step_key': rn.get('step_key')}
            r = rr; why = f'stock score rn{score(rn)} > rr{score(rr)}'
        other = rn if r is rr else rr
    else:
        r = bi.classify_db1(c, res_, g); other = None; why = 'single'
    if r is None:
        continue
    rec = {'id': r['id'][:12], 'class': r['class'], 'reused': r['reused'], 'reuse_from': r.get('reuse_from'), 'code': r.get('converter_code'),
           'cov_m': r.get('coverage_members'), 'cov_all': r.get('coverage_all'), 'parts_source': r.get('parts_source'), 'parts_step': r.get('parts_step'),
           'reasons': r['reasons'], 'n_iss_st_need': len(r['issues']) + len(r['standins']) + len(r['needs']), 'why': why,
           'step_key': (r.get('step_key') or '')[-60:]}
    if other is not None:
        rec['other'] = {'class': other['class'], 'reused': other['reused'], 'code': other.get('converter_code'), 'cov_m': other.get('coverage_members'),
                        'cov_all': other.get('coverage_all'), 'reasons': other['reasons'],
                        'n_iss_st_need': len(other['issues']) + len(other['standins']) + len(other['needs'])}
    for k in ('coverage_basis', 'windows_join'):
        if r.get(k) is not None:
            rec[k] = r[k]
    out.append(rec)
    print(json.dumps(rec))
if a.json:
    json.dump(out, open(a.json, 'w'), indent=1)
