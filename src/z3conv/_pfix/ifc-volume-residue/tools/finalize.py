#!/usr/bin/env python3
"""fill the README placeholders with the per-model table and the combined-patch table"""
import os, subprocess
H = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(H, '..', 'README.md')
s = open(R).read()
t = subprocess.run(['python3', os.path.join(H, 'table.py')], capture_output=True, text=True, cwd=os.path.join(H, '..', 'data')).stdout
c = subprocess.run(['python3', os.path.join(H, 'combined_table.py')], capture_output=True, text=True).stdout
cmp_ = subprocess.run(['python3', os.path.join(H, 'compare_p.py')], capture_output=True, text=True, env=dict(os.environ, LABEL='dev3pc')).stdout.strip().splitlines()[-1]
lines = t.strip().splitlines()
counts = lines[-1]
table = '\n'.join(lines[:-1]).strip()
sect = ("Per model (live = the index row as graded today; dev3 / patched = this run through the fleet worker + classifier; "
        "census v3 = the proposed census on the same STEP; 'oom' = the dev3 memory blow-up of 5.3):\n\n" + table +
        "\n\nClass-1 count over the 36 converted models: live %d, dev3 %d, dev3 + patches %d, dev3 + patches + census v3 %d "
        "(patched = both patches for the 7 models of the combined run, patch 1 for the others; patch 2 is a no-op there: "
        "no composite curve with an empty segment)." % tuple(__import__('json').loads(counts)[k] for k in ('before_1', 'dev3_1', 'dev3p_1', 'v3_1')))
s = s.replace('TABLE_PLACEHOLDER', sect)
s = s.replace('COMBINED_PLACEHOLDER', "Both patches together (combined file = dev3 + patch 1 + patch 2), 7 models:\n\n" + c.strip() +
              "\n\nPer-part comparison dev3 vs combined (gid-joined step_parts): " + cmp_ + ".")
open(R, 'w').write(s)
print('README filled')
