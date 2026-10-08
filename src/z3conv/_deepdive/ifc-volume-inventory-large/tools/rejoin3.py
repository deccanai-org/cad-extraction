#!/usr/bin/env python3
"""3-way per-part volume check on the same stored STEP part lists (S3 detail step_parts):
  A = census v1 parts (S3 detail, as graded) + upstream join (kit 15:35, what the coordinator re-join computes today)
  B = upstream census v2 (kit 15:35: HSS / T fillets, openings -> no analytic value) + upstream join
  C = census v3 (this deep dive: openings subtracted, exact profile areas) + join v3 (interval support)
usage: rejoin3.py WORKDIR"""
import sys, os, json, importlib.util, collections
W = sys.argv[1]
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'patches')
def lm(path, name):
    import importlib.machinery
    ld = importlib.machinery.SourceFileLoader(name, path)
    s = importlib.util.spec_from_loader(name, ld); m = importlib.util.module_from_spec(s); ld.exec_module(m); return m
up = lm(os.path.join(P, 'baseline', 'grade_join.upstream.py'), 'gj_up'); v3 = lm(os.path.join(P, 'out', 'ifc__grade_join.py.patched'), 'gj_v3')
sets = []
for line in open(os.path.join(W, 'dl_list.txt')):
    rid = line.split('\t')[0]; s8 = rid.replace('ifc-', '')[:8]
    sets.append(('vol25', rid, os.path.join(W, 'det', rid), os.path.join(W, 'cenU', s8), os.path.join(W, 'cen3', s8)))
for line in open(os.path.join(W, 'wide', 'list.txt')):
    rid = line.split('\t')[0]; s8 = rid[4:12]
    sets.append(('wide40', rid, os.path.join(W, 'wide', 'det', rid), os.path.join(W, 'wide', 'cenU', s8), os.path.join(W, 'wide', 'cen3', s8)))
T = collections.defaultdict(collections.Counter); rows = []
def vo(j):
    v = j['volume']; return v['checked'], v['outside_5pct'] + (v.get('outside_curved_gross') or 0), v.get('checked_interval', 0)
for grp, rid, det, cu, c3 in sets:
    if not all(os.path.exists(x) for x in (det + '.step_parts.jsonl.gz', det + '.src_parts.jsonl.gz', cu + '.src_parts.jsonl.gz', c3 + '.src_parts.jsonl.gz')):
        print('missing', rid); continue
    S = up.load(det + '.step_parts.jsonl.gz')
    a = vo(up.join(up.load(det + '.src_parts.jsonl.gz'), S)); b = vo(up.join(up.load(cu + '.src_parts.jsonl.gz'), S)); c = vo(v3.join(v3.load(c3 + '.src_parts.jsonl.gz'), S))
    g = grp + ('_far_coord_old_step' if '1481043e' in rid else '')
    for k, x in (('A', a), ('B', b), ('C', c)):
        T[g][k + '_checked'] += x[0]; T[g][k + '_out'] += x[1]; T[g][k + '_models_out'] += x[1] > 0
    T[g]['C_interval'] += c[2]; T[g]['models'] += 1
    rows.append((g, rid[:20], a, b, c))
print('%-28s %-20s %18s %18s %22s' % ('set', 'model', 'A chk/out', 'B chk/out', 'C chk/out/interval'))
for g, rid, a, b, c in rows:
    print('%-28s %-20s %10d/%-7d %10d/%-7d %10d/%-5d/%-5d' % (g, rid, a[0], a[1], b[0], b[1], c[0], c[1], c[2]))
for g, t in T.items():
    print(g, dict(t))
