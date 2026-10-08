#!/usr/bin/env python3
"""census3_eval.py WORKDIR CENSUS_V3.py - run the v3 census on the converted IFC of a dev3 work dir, join with the dev3
STEP parts (grade_join from the kit) -> outside counts v2 vs v3 + the remaining outside parts; also checks every new
v3 analytic value against the exact kernel B-rep volume (fullscan-style) for a sample"""
import sys, os, json, gzip, subprocess, collections
sys.path.insert(0, os.environ.get('KIT', '/work/agentwork/ifc-volume-residue/pkg/kit'))
import grade_join as G
wd, cen = sys.argv[1], sys.argv[2]
ifc = next((os.path.join(wd, n) for n in ('hdr.ifc', 'merged.ifc', 'schema.ifc', 'unz.ifc', 'in.bin') if os.path.exists(os.path.join(wd, n))), None)
out3 = os.path.join(wd, 'census3.json'); parts3 = os.path.join(wd, 'src_parts3.jsonl.gz')
r = subprocess.run(['/opt/conv/env/bin/python', cen, ifc, out3, '--parts', parts3], capture_output=True, text=True)
if r.returncode:
    print(json.dumps({'wd': wd, 'error': r.stderr[-800:]})); sys.exit(0)
step = G.load(os.path.join(wd, 'step_parts.jsonl.gz'))
s2 = G.load(os.path.join(wd, 'src_parts.jsonl.gz')); s3 = G.load(parts3)
j2, j3 = G.join(s2, step), G.join(s3, step)
v2, v3 = j2['volume'], j3['volume']
by2 = {p['gid']: p for p in s2}
new_an = sum(1 for p in s3 if p.get('an') and not (by2.get(p['gid']) or {}).get('an'))
c3 = json.load(open(out3))
print(json.dumps({'wd': os.path.basename(wd.rstrip('/')), 'apps': c3.get('applications'), 'v2': [v2['outside_5pct'] + v2['outside_curved_gross'], v2['checked']],
                  'v3': [v3['outside_5pct'] + v3['outside_curved_gross'], v3['checked']], 'new_an': new_an, 'rebased': c3.get('quantities_rebased'),
                  'with_an': [sum(1 for p in s2 if p.get('an')), sum(1 for p in s3 if p.get('an'))], 'worst3': v3['worst'][:8]}))
