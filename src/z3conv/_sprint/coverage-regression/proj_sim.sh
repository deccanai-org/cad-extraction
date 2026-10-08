#!/bin/bash
# projected index: production results + A/B full_fix results (code i + db1bolts guard + overlay ext) for the 13 A/B models
cd /Users/dhiren/Downloads/Deccan/z3conv/_sprint/coverage-regression
rm -rf db1res_proj && mkdir db1res_proj && cp db1res3/*.json db1res_proj/
python3 - <<'PY'
import json, glob, os
for p in glob.glob('abres/full_fix/*.json'):
    r = json.load(open(p))
    if r.get('status') != 'ok':
        continue
    r['code'] = 'z3-db1-2026-10-01i+cr'
    json.dump(r, open('db1res_proj/' + os.path.basename(p), 'w'))
    print('override', os.path.basename(p)[:12])
PY
python3 sim_index2.py patch/out/build_index.coord_2351.patched.py state4/contents_db1.jsonl.gz db1res_proj graderes3 --rules deployed2/rules.json --wj wjres --json sim_projected.json > /dev/null 2>&1
python3 sim_index2.py patch/out/build_index.coord_2351.py state4/contents_db1.jsonl.gz db1res_proj graderes3 --rules deployed2/rules.json --json sim_projected_stockindex.json > /dev/null 2>&1
