#!/usr/bin/env python3
"""before/after of the volume join: fleet src_parts (or local original census) vs patched census, both joined with the fleet
STEP parts. usage: rejoin_compare.py ORIG_JOIN_PY NEW_JOIN_PY ORIGDIR NEWDIR STEPDIR ID..."""
import sys, json, importlib.util


def mod(p, n):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


oj, nj = mod(sys.argv[1], 'oj'), mod(sys.argv[2], 'nj')
od, nd, sd = sys.argv[3:6]
for i in sys.argv[6:]:
    step = oj.load(f'{sd}/{i}.step_parts.jsonl.gz')
    a = oj.join(oj.load(f'{od}/{i}.src_parts.jsonl.gz'), step)
    b = nj.join(nj.load(f'{nd}/{i}.src_parts.jsonl.gz'), step)
    va, vb = a['volume'], b['volume']
    print(json.dumps({'id': i[:16], 'mode': a['mode'], 'cov_all': [a['coverage']['all'], b['coverage']['all']],
                      'checked': [va['checked'], vb['checked']], 'outside_5pct': [va['outside_5pct'], vb['outside_5pct']],
                      'outside_curved': [va['outside_curved'], vb['outside_curved']], 'curved_gross': vb.get('outside_curved_gross'),
                      'median': [va.get('median'), vb.get('median')], 'worst_after': vb['worst'][:3]}))
