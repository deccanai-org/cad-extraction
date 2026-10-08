#!/usr/bin/env python3
"""make_readme.py OUTDIR -> README.md tables from data/ab553/compare553.json (+ v553r reruns), data/ab/compare.json (v5.4 A/B,
earlier patch revision) and data/projection/agg_all.json."""
import json, os, sys, glob
D = sys.argv[1]
ab = json.load(open(os.path.join(D, 'data/ab553/compare553.json')))
r_over = {}
for f in glob.glob(os.path.join(D, 'data/ab553/v553r/*/*_manifest.json')):
    M = json.load(open(f)); c = M['counts']; s = M['skipped']; rb = M.get('readback') or {}
    r_over[os.path.basename(os.path.dirname(f))] = dict(cls=M['class'], corpus=M['corpus'], skipped=s['total'], by=s['by_reason'],
                                                        ratio=(M.get('weight_check') or {}).get('ratio'), rb_valid=rb.get('valid'),
                                                        rb_solids=rb.get('solids'), exact=c.get('pieces_exact'), approx=c.get('pieces_approx'))
SHORT = {'absurd_extent_corrupt_source_geometry': 'absurd', 'no_usable_special_geometry': 'no_usable', 'fallback_over_5x_source_weight': 'over_5x',
         'fallback_builder_failed': 'builder_failed', 'reference_part_no_closed_brep': 'ref_no_closed', 'reference_time_budget_exceeded': 'ref_budget',
         'source_piece_has_no_geometry': 'src_no_geometry', 'source_piece_file_missing': 'src_file_missing', 'source_piece_zero_size': 'src_zero_size',
         'source_mesh_open': 'src_mesh_open', 'exact_solid_invalid_at_placement': 'invalid_at_placement'}


def short_live(lv):
    if not lv:
        return 'control (class 1)'
    import re
    iss = next((i for i in lv['issues'] if i.startswith('pieces_not_built')), '')
    m = re.match(r'pieces_not_built:(\d+) \((.*)\)', iss)
    rs = {k: int(v) for k, v in (kv.rsplit(':', 1) for kv in m.group(2).split(','))} if m else {}
    return f"{lv['conv']}, class {lv['cls']}: {m.group(1) if m else '?'} not built ({by(rs)})"


def by(x):
    return ', '.join(f"{SHORT.get(k, k)} {v:,}" for k, v in sorted((x or {}).items(), key=lambda kv: -kv[1])) or '-'


def cell(x, ref=False):
    if x.get('cls') is None:
        return f"({x.get('rc') or 'not run'})", '', '', '', ''
    sol = f"{x.get('rb_valid'):,} / {x.get('rb_solids'):,}" if x.get('rb_solids') is not None else '-'
    if ref:
        built = f"ref {x.get('ref') or 0:,} (open {x.get('ref_open') or 0:,}, face sets {x.get('ref_fs') or 0:,})"
    else:
        built = f"exact {x.get('exact') or 0:,} / approx {x.get('approx') or 0:,}"
    return f"{x['cls']}{x['corpus']}", f"{x['skipped']:,}" + (f" ({by(x['by'])})" if x['skipped'] else ''), built, sol, \
        (f"{x['ratio']:.4f}" if x.get('ratio') else '-')


lines = ['| job | live result | run | class | skipped (reasons) | pieces written | read-back valid / solids | steel / SDS2 |',
         '|---|---|---|---|---|---|---|---|']
order = sorted(ab, key=lambda r: (0 if (r['v553'].get('corpus') == 'R') else 1, r['job'].lower()))
for r in order:
    lv = r['live']
    live = short_live(lv)
    ref = r['v553'].get('corpus') == 'R'
    a = cell(r['v553'], ref); b = cell(r['v553q'], ref)
    lines.append(f"| {r['job']} | {live} | v5.5.3 | {a[0]} | {a[1]} | {a[2]} | {a[3]} | {a[4]} |")
    if r['v553q'].get('cls') is None and r['job'] in r_over:
        x = r_over[r['job']]
        lines.append(f"| | | **+ patch** (v553r tree) | {x['cls']}{x['corpus']} | {x['skipped']:,} ({by(x['by'])}) | ref / steel see §2.3 | "
                     f"{x['rb_valid'] or 0:,} / {x['rb_solids'] or 0:,} | - |")
        continue
    lines.append(f"| | | **+ patch** | {b[0]} | {b[1]} | {b[2]} | {b[3]} | {b[4]} |")
    if r['job'] in r_over:
        x = r_over[r['job']]
        lines.append(f"| | | + patch (final, weight tally) | {x['cls']}{x['corpus']} | {x['skipped']} | exact {x['exact']:,} / approx {x['approx']:,} | "
                     f"{x['rb_valid']:,} / {x['rb_solids']:,} | {x['ratio']:.4f} |")
open(os.path.join(D, 'data/ab553/table.md'), 'w').write('\n'.join(lines) + '\n')

# final tree (v553s) on the feature jobs and controls, against v5.5.3
F = ['| job | v5.5.3: class, skipped, read-back valid / solids, steel / SDS2 | final patch: class, skipped, read-back valid / solids, steel / SDS2 | exact / approx (v5.5.3 -> final) | wall s (v5.5.3 / final) |',
     '|---|---|---|---|---|']
base = {r['job']: r['v553'] for r in ab}
for f in sorted(glob.glob(os.path.join(D, 'data/ab553/v553s/*/*_manifest.json'))):
    j = os.path.basename(os.path.dirname(f)); a = base.get(j) or {}
    M = json.load(open(f)); c = M['counts']; s_ = M['skipped']; rb = M.get('readback') or {}
    rcf = os.path.join(os.path.dirname(f), 'rc.txt')
    rc = open(rcf).read().strip() if os.path.exists(rcf) else ''
    w = (M.get('weight_check') or {}).get('ratio')
    F.append(f"| {j} | {a.get('cls')}{a.get('corpus')}, {a.get('skipped')}, {a.get('rb_valid'):,} / {a.get('rb_solids'):,}, {a.get('ratio') or '-'} | "
             f"{M['class']}{M['corpus']}, {s_['total']}" + (f" ({by(s_['by_reason'])})" if s_['total'] else '') +
             f", {rb.get('valid'):,} / {rb.get('solids'):,}, {w if w else '-'} | {a.get('exact')} / {a.get('approx')} -> {c.get('pieces_exact')} / {c.get('pieces_approx')} | "
             f"{(a.get('rc') or '').split('wall=')[-1]} / {rc.split('wall=')[-1]} |")
open(os.path.join(D, 'data/ab553/table_final.md'), 'w').write('\n'.join(F) + '\n')

old = json.load(open(os.path.join(D, 'data/ab/compare.json')))
L2 = ['| job | v5.4: class, skipped | v5.4 + patch (earlier revision): class, skipped | read-back solids |', '|---|---|---|---|']
for r in sorted(old, key=lambda r: r['job'].lower()):
    a, b = r['a'], r['b']
    if a.get('cls') is None or b.get('cls') is None:
        continue
    rba, rbb = (a.get('rb') or {}).get('solids'), (b.get('rb') or {}).get('solids')
    L2.append(f"| {r['job']} | {a['cls']}{a['corpus']}, {a['skipped']:,} ({by(a['by'])}) | {b['cls']}{b['corpus']}, {b['skipped']:,} ({by(b['by'])}) | "
              f"{rba:,} -> {rbb:,} |")
open(os.path.join(D, 'data/ab/table.md'), 'w').write('\n'.join(L2) + '\n')
T = open(os.path.join(D, 'job/stage2/README.template.md')).read()
T = T.replace('{AB_TABLE}', '\n'.join(lines)).replace('{AB54_TABLE}', '\n'.join(L2))
T = T.replace('{FINAL_RUNS}', 'Final tree (exactly `sds2-pieces-not-built.diff`: the tested tree + the 2.6 weight tally + the touching-wall case of 2.4) '
              'on the feature jobs and the controls, against v5.5.3. Wall times depend on the shared box load and are not a benchmark.\n\n' + '\n'.join(F))
open(os.path.join(D, 'README.md'), 'w').write(T)
print(len(lines) - 2, len(L2) - 2, len(F) - 2)
