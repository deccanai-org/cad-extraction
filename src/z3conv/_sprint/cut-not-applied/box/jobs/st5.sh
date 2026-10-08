#!/bin/bash
cd /work/agentwork/cut-not-applied; echo "kitnp7 corpus $(ls convall/kitnp7/*/conv.json 2>/dev/null | wc -l)/106"; for d in pipes5/*/*; do [ -f $d/pipe.json ] && echo "done $d" || echo "run  $d"; done; uptime; free -g | sed -n 2p
python3 - <<'P'
import json, gzip, glob, re, collections
c = collections.Counter(); m = 0
for f in glob.glob('convall/kitnp5/*/convert.json.parts.json.gz'):
    for p in json.load(gzip.open(f, 'rt')):
        if p[3] != 'written' or not p[1]: continue
        mm = re.match(r'^(?:PL|FL|FB|BL|PLT|FLT|PLATE|BPL|FPL|FLAT)\s*(\d+(?:\.\d+)?)\s*[X\*x]\s*(\d+(?:\.\d+)?)$', p[1].strip().upper())
        if mm:
            a, b = float(mm.group(1)), float(mm.group(2)); c['plate_axb'] += 1
            if a > b: c['a_gt_b'] += 1; c['a_gt_b_models'] += 0
            if a > b and p[6]: c['a_gt_b_with_cuts_or_holes'] += 1
print(dict(c))
P
