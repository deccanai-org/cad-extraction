#!/usr/bin/env python3
"""Offline before/after of the classifier: runs the classify_* functions of two build_index.py versions (each with its sibling
grade_join.py) over the same local copies of scan/contents_*.jsonl.gz, {ifc,db1,sds2}/results and grade/results, with the
rejoin of reused IFC/DB1 grades done locally from the stored detail files (as build_index.rejoin_grades does from S3).
'after' uses the re-census src_parts (patched ifc_census.py) where present (RECENSUS dirs), else the fleet src_parts.
usage: simulate_index.py BEFORE_DIR AFTER_DIR WORKDIR OUT.json"""
import sys, os, json, gzip, glob, importlib.util, collections

before_dir, after_dir, wd, out = sys.argv[1:5]
os.environ['INDEX_WORK'] = os.path.join(wd, 'sim_index_work')


def load_mod(d, name):
    sys.modules.pop('grade_join', None)
    spec = importlib.util.spec_from_file_location(name, os.path.join(d, 'build_index.py'))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m._gj = sys.modules.pop('grade_join')
    assert os.path.dirname(os.path.abspath(m._gj.__file__)) == os.path.abspath(d), m._gj.__file__
    return m


def jl(p):
    with gzip.open(p, 'rt') as f:
        return [json.loads(l) for l in f if l.strip()]


summ = json.load(open(os.path.join(wd, 'idx2', 'index_summary.json')))
contents = {p: jl(os.path.join(wd, 'scan', f'contents_{p}.jsonl.gz')) for p in ('ifc', 'db1', 'sds2')}
res = {p: {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(wd, 'res', p, '*.json'))} for p in ('ifc', 'db1', 'sds2')}
grades0 = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(wd, 'res', 'grade', '*.json'))}
RECENSUS = [os.path.join(wd, d) for d in ('recensus', 'recensus_c1')]


def src_parts(gid, patched):
    if patched:
        for d in RECENSUS:
            p = os.path.join(d, f'{gid}.src_parts.jsonl.gz')
            if os.path.exists(p):
                return jl(p), True
    p = os.path.join(wd, 'stepparts', f'{gid}.src_parts.jsonl.gz')
    return (jl(p), False) if os.path.exists(p) else (None, False)


def run(m, patched):
    m.RULES = dict(m.DEFAULT_RULES); m.RULES.update(summ.get('rules') or {})
    grades = json.loads(json.dumps(grades0))
    resl = json.loads(json.dumps(res))
    n_rejoin = n_recensus = 0
    for gid, r in grades.items():                     # = build_index.rejoin_grades, local files
        if r.get('pipeline') not in ('ifc', 'db1') or r.get('status') != 'ok' or (r.get('join') or {}).get('mode') == 'gid':
            continue
        sp = os.path.join(wd, 'stepparts', f'{gid}.step_parts.jsonl.gz')
        src, rc = src_parts(gid, patched)
        if src is None or not os.path.exists(sp):
            continue
        r['join'] = m._gj.join(src, jl(sp)); n_rejoin += 1; n_recensus += rc
    if patched:                                       # new IFC conversions re-graded with the patched census + join
        for i, r in resl['ifc'].items():
            gid = 'ifc-' + i
            if r.get('status') != 'ok' or not r.get('join'):
                continue
            src, rc = src_parts(gid, True)
            sp = os.path.join(wd, 'stepparts', f'{gid}.step_parts.jsonl.gz')
            if rc and os.path.exists(sp):
                r['join'] = m._gj.join(src, jl(sp)); n_recensus += 1
    rows = {}
    for pipe, fn in (('ifc', m.classify_ifc), ('db1', m.classify_db1), ('sds2', m.classify_sds2)):
        for c in contents[pipe]:
            row = fn(c, resl[pipe].get(c['id']), grades.get(f'{pipe}-{c["id"]}'))
            if row is not None:
                rows[(pipe, c['id'])] = row
    return rows, n_rejoin, n_recensus


mb, ma = load_mod(before_dir, 'bi_before'), load_mod(after_dir, 'bi_after')
rb, nb, _ = run(mb, False)
ra, na, nrc = run(ma, True)
trans = collections.Counter(); detail = collections.defaultdict(list)
key = lambda r: (r['reasons'] or r['issues'] or [s['type'] for s in r['standins']] or r['needs'] or [''])[0].split(':')[0].split(' (')[0]
for k in rb:
    a, b = ra[k], rb[k]
    trans[(k[0], b['class'], a['class'])] += 1
    if a['class'] != b['class'] or (a['class'] == 3 and b['class'] == 3 and key(a) != key(b)):
        detail[f'{k[0]} {b["class"]}->{a["class"]}'].append({'id': k[1], 'before': key(b), 'after': key(a),
                                                            'after_new': sorted(set(a['issues']) - set(b['issues']))[:4],
                                                            'before_gone': sorted(set(b['issues']) - set(a['issues']))[:4]})
reasons_after = collections.Counter(); reasons_before = collections.Counter()
for k in rb:
    if rb[k]['class'] == 3: reasons_before[(k[0], key(rb[k]))] += 1
    if ra[k]['class'] == 3: reasons_after[(k[0], key(ra[k]))] += 1
res_ = {'rejoined_before': nb, 'rejoined_after': na, 'recensus_used': nrc,
        'classes_before': {p: dict(collections.Counter(str(r['class']) for (pp, _), r in rb.items() if pp == p)) for p in ('ifc', 'db1', 'sds2')},
        'classes_after': {p: dict(collections.Counter(str(r['class']) for (pp, _), r in ra.items() if pp == p)) for p in ('ifc', 'db1', 'sds2')},
        'transitions': {f'{p} {b}->{a}': n for (p, b, a), n in sorted(trans.items(), key=str) if b != a},
        'class3_reasons_before': {f'{p}:{k}': n for (p, k), n in reasons_before.most_common()},
        'class3_reasons_after': {f'{p}:{k}': n for (p, k), n in reasons_after.most_common()},
        'changed': {k: v for k, v in detail.items()}}
json.dump(res_, open(out, 'w'), indent=1, default=str)
print(json.dumps({k: res_[k] for k in ('rejoined_before', 'rejoined_after', 'recensus_used', 'classes_before', 'classes_after', 'transitions')}, indent=1))
