#!/usr/bin/env python3
"""Markdown evidence table from the case dirs: grader counters (kit step_check.py) for
  fleet   = the fleet's own validate block (result.json)          out    = reused / fleet STEP re-checked locally
  split4  = out.stp repaired by tools/split_lumps_step.py         wA, wB = kit ifc2step5.py vs patched writer from source
  sfx     = sibling ifc-invalid-solids step_shellfix snapshot     v6     = ifc_improver ifc2step6 snapshot
cell = solids / invalid / non-positive-volume"""
import json, os, sys
D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
cases = sys.argv[1:] or ['c14e58', 'c050de8', 'c236247', 'c0294b4', 'c04a42f', 'c063b74', 'cddaae9', 'c09cbd0', 'c148104',
                         'c0e9244', 'c061413', 'c3d1cde', 'c15af92']
tags = ['fleet', 'split4', 'wA', 'wB', 'sfx', 'v6']
print('| case | model id | app | ' + ' | '.join(tags) + ' |')
print('|' + '---|' * (3 + len(tags)))
for c in cases:
    d = os.path.join(D, c)
    if not os.path.isdir(d):
        continue
    r = json.load(open(os.path.join(d, 'result.json')))
    app = ' '.join((r.get('census') or {}).get('applications') or [])[:18]
    cells = []
    for t in tags:
        if t == 'fleet':
            v = r.get('validate') or {}
        else:
            p = os.path.join(d, 'chk_%s.json' % t)
            v = json.load(open(p)) if os.path.exists(p) else None
        cells.append('%s / %s / **%s**' % (v.get('solids'), v.get('invalid'), v.get('nonpos_vol')) if v else '-')
    print('| %s | %s | %s | %s |' % (c, r.get('id', '')[:16], app, ' | '.join(cells)))
