#!/usr/bin/env python3
"""Re-classify the npv sample after the lump-split repair, with the index builder's own rules (coord/build_index.py
step_checks + vol_issues + finish_class), using
  data/class_2_now.jsonl.gz          current index rows (issues, coverage, standins, needs)
  batch/<id>.json                    after-repair step_check counters + re-run grade_join (batch_one.sh)
Only the signals the repair can change are recomputed: invalid_solids, non_positive_volume_solids, roots_not_transferred,
coverage (join on the repaired STEP parts), parts_outside_volume_tolerance; every other issue/standin/need is kept.
usage: quantify.py [batch_dir] -> table + data/quantify.json"""
import json, gzip, glob, os, sys, collections
B = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bd = sys.argv[1] if len(sys.argv) > 1 else os.path.join(B, 'batch')
rows = {}
for l in gzip.open(os.path.join(B, 'data/class_2_now.jsonl.gz'), 'rt'):
    r = json.loads(l)
    if r['pipeline'] == 'ifc':
        rows[r['id']] = r
RECOMPUTED = ('invalid_solids', 'non_positive_volume_solids', 'roots_not_transferred', 'parts_outside_volume_tolerance')
out = []; agg = collections.Counter(); moves = collections.Counter()
for f in sorted(glob.glob(os.path.join(bd, '*.json'))):
    o = json.load(open(f))
    sid = o['id'][4:] if o['id'].startswith('ifc-') else o['id']
    r = rows.get(sid)
    if r is None or 'after' not in o:
        agg['no_row_or_no_after'] += 1; continue
    a = o['after']
    before_issues = [i.split(':')[0] for i in r['issues']]
    issues = [i for i in r['issues'] if i.split(':')[0] not in RECOMPUTED]
    if a.get('read_status') != 'ok':
        issues.append('step_read_failed_after')
    inv = a.get('invalid_solids_est', a.get('invalid'))
    if inv:
        issues.append(f'invalid_solids:{inv}')
    if a.get('nonpos_vol'):
        issues.append(f'non_positive_volume_solids:{a["nonpos_vol"]}')
    if a.get('empty_roots'):
        issues.append(f'roots_not_transferred:{a["empty_roots"]}')
    cov = dict(member=r.get('coverage_members'), connection=r.get('coverage_connections'), other=r.get('coverage_other'),
               all=r.get('coverage_all'))
    j = o.get('join')
    if j and not j.get('error'):
        cov = j.get('coverage') or cov
        vol = j.get('volume') or {}
        n = vol.get('outside_5pct') or 0
        if n > 0:
            issues.append(f'parts_outside_volume_tolerance:{n}/{vol.get("checked")}')
    elif 'parts_outside_volume_tolerance' in before_issues:
        issues += [i for i in r['issues'] if i.startswith('parts_outside_volume_tolerance')]
    partial = any(x is not None and x < 1.0 for x in cov.values())
    cls = 2 if (partial or r['standins'] or r['needs'] or issues) else 1
    cm = cov.get('member')
    if cm is not None and cm < 0.5:
        cls = 3
    only_npv = set(before_issues) == {'non_positive_volume_solids'}
    bucket = 'npv_only' if only_npv else '+'.join(sorted(set(before_issues)))
    rec = {'id': sid, 'bucket': bucket, 'class_after': cls, 'issues_before': r['issues'], 'issues_after': issues,
           'coverage_after': cov, 'split': o.get('split'), 'after': {k: a.get(k) for k in ('solids', 'invalid', 'nonpos_vol', 'empty_roots')}}
    out.append(rec)
    moves[(bucket, cls)] += 1
    agg['models'] += 1; agg['class1_after'] += cls == 1
    agg['npv_cleared'] += not a.get('nonpos_vol')
    agg['invalid_cleared_of_those_with_invalid'] += ('invalid_solids' in before_issues and not inv)
    agg['had_invalid'] += 'invalid_solids' in before_issues
    agg['solids_npv_after'] += a.get('nonpos_vol') or 0
    agg['solids_invalid_after'] += inv or 0
print(json.dumps(dict(agg), indent=1))
by = collections.defaultdict(collections.Counter)
for (b, c), n in moves.items():
    by[b][c] += n
for b, c in sorted(by.items(), key=lambda x: -sum(x[1].values())):
    print(f'{sum(c.values()):4d}  {b:70s} -> class1 {c[1]:4d}  class2 {c[2]:4d}  class3 {c[3]:3d}')
rest = collections.Counter()
for r in out:
    if r['class_after'] != 1:
        rest[tuple(sorted(set(i.split(':')[0] for i in r['issues_after'])))] += 1
print('remaining class-2 issue sets:')
for k, v in rest.most_common():
    print(f'{v:4d}  {k}')
json.dump({'agg': dict(agg), 'models': out}, open(os.path.join(B, 'data/quantify.json'), 'w'), indent=0)
