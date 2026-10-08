#!/usr/bin/env python3
"""assemble before/after tables (markdown) from the run case.json files (data/runs/<label>/<id16>/case.json)"""
import json, glob, os, sys
R = '/Users/dhiren/Downloads/Deccan/z3conv/_pfix/ifc-verification-residue'
RUNS = R + '/data/runs'


def case(label, i16):
    try:
        return json.load(open(f'{RUNS}/{label}/{i16}/case.json'))
    except Exception:
        return None


def cell(c):
    if c is None:
        return '-'
    if c.get('class') is None:
        return 'n/a (%s)' % (c.get('fail_reason') or c.get('error', '')[:40])
    st = c.get('stats') or {}
    bits = [str(c['class'])]
    iss = [x for x in (c.get('issues') or [])]
    sti = ['%s:%s' % (s['type'].replace('v6_', ''), s['count']) for s in c.get('standins') or []]
    if iss or sti:
        bits.append(', '.join(iss + sti))
    lv = st.get('levels') or {}
    bits.append('L ' + '/'.join('%s%s' % (k[1:], ':%d' % v) for k, v in sorted(lv.items())))
    if st.get('out_bytes'):
        bits.append('%.1f MB' % (st['out_bytes'] / 1e6))
    return ' ; '.join(bits)


def fleet_cell(i):
    """latest fleet result (6.0.1 / 6.1.0-rc) from data/res601"""
    fn = glob.glob(f'{R}/data/res601/{i}*.json')
    if not fn:
        return '-'
    d = json.load(open(fn[0]))
    st = ((d.get('attempts') or [{}])[-1].get('stats') or {})
    return '%s: L %s' % (st.get('converter', '?').replace('ifc2step6 ', ''), '/'.join('%s%s' % (k[1:], ':%d' % v) for k, v in sorted((st.get('levels') or {}).items())))


out = []
T = json.load(open(R + '/job/targets_mnc.json'))
out.append('## members not converted (16, all class 3 live: reused old-writer STEPs)\n')
out.append('| model | size | live (class, reasons) | fleet now (6.1.0-rc) | dev3 | dev3+vr, stock grader | dev3+vr, V6_FAR_VERIFY=1 + grader rule |')
out.append('|---|---|---|---|---|---|---|')
for o in sorted(T, key=lambda o: o['size']):
    i = o['id'][:16]
    cam = i.startswith('4bbcc615')
    out.append('| %s %s | %.1f MB | %s %s | %s | %s | %s | %s |' % (
        i[:12], os.path.basename(o['path'])[:28], o['size'] / 1e6, o['was_class'], ', '.join(o['was_reasons'] + o['was_issues'][:2]),
        fleet_cell(i), cell(case('mnc_dev3', i)), cell(case('cam_vr4', i) if cam else (case('far_vr9', i) or case('far_vr8', i))), cell(case('far_vr9F_gp', i) or case('far_vr8F_gp', i)) if not cam else '(not far)'))
open(R + '/results/members_not_converted.md', 'w').write('\n'.join(out) + '\n')
out = ['## L2-heavy models (10; 6.0.1 wrote L2-alt-source parts)\n', 'Last column: the read-back cap forced to 1 MB, so every STEP takes the large-file path; the only issue left is the forced not_read_back_large_file, and per_part_verification_pending is gone (census join from the converter read-back, identical to the step_check join on 10/10).\n', '| model | size | live | dev3 | dev3+vr | dev3+vr, read-back cap 1 MB + worker hook (join from converter read-back) |', '|---|---|---|---|---|---|']
for o in json.load(open(R + '/job/targets_l2.json')):
    i = o['id'][:16]
    out.append('| %s %s | %.2f MB | %s L2:%s | %s | %s | %s |' % (i[:12], os.path.basename(o['path'])[:26], o['size'] / 1e6, o['was_class'], o['was_l2'],
                                                         cell(case('l2_dev3', i)), cell(case('l2_vr8', i)), cell(case('l2_vr4_rb1', i))))
open(R + '/results/l2_models.md', 'w').write('\n'.join(out) + '\n')
out = ['## per-part verification pending: models re-run (STEP over the 1 GB read-back cap or read-back OOM in the live index)\n',
       '| model | IFC size | live STEP (v5 / 6.0.1) | dev3 | dev3+vr (converter peak RSS, STEP size, verdict of the ordinary fleet read-back) |', '|---|---|---|---|---|']
NOTE = {'beeeacea7d2d': 'memory runaway: 173 GB RSS in the kernel pass after about 10 min (killed)',
        '1c61df42e527': 'not completed (run stopped by me with the Seaport batch; was at 0.8 GB)',
        'af3c44bd76cf': 'see bop_dev3 below'}
RUNS_ = {'beeeacea7d2d': 'ppv_vr3', '1c61df42e527': 'ppv_vr3', '2bcaa3013d92': 'ppv_vr3', '2c0f7a89ddf2': 'stockton_vr7', 'af3c44bd76cf': 'bop_vr9'}
for o in json.load(open(R + '/job/targets_ppv2.json')):
    i = o['id'][:16]
    if o['id'][:12] not in RUNS_:
        continue
    c3 = case(RUNS_[o['id'][:12]], i) or (case('ppv_vr4b', i) if o['id'][:12] in ('2c0f7a89ddf2', 'af3c44bd76cf') else None)
    st = (c3 or {}).get('stats') or {}
    extra = ' ; converter peak %s MB, %s s' % (st.get('peak_rss_mb'), st.get('total_sec')) if st else ''
    d3 = case('bop_dev3', i) if o['id'][:12] == 'af3c44bd76cf' else None
    out.append('| %s %s | %.0f MB | %.0f MB (%s) | %s | %s%s |' % (i[:12], os.path.basename(o['path'])[:26], o['size'] / 1e6, (o.get('step_bytes') or 0) / 1e6,
                                                ', '.join(o['was_issues']), cell(d3) if d3 else NOTE.get(o['id'][:12], 'not run'), cell(c3), extra))
open(R + '/results/per_part_pending.md', 'w').write('\n'.join(out) + '\n')
print(open(R + '/results/members_not_converted.md').read())
