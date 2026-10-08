"""render_poly.py ID: polybeam before / after: the deployed .i STEP (first segment only) and the patched STEP (full polyline), same window"""
import json, os, sys, gzip, subprocess
import numpy as np
W = os.path.dirname(os.path.abspath(__file__)); os.chdir(W)
a = sys.argv[1]; i = [f[:-4] for f in os.listdir('src') if f.startswith(a)][0]
pc = json.load(open('report/proof_cmp.json'))[i]
P = [json.loads(l) for l in gzip.open(f'proof/{a}_jfix2.parts.jsonl.gz', 'rt')]
D = [json.loads(l) for l in gzip.open(f'det/{i}.i.step_parts.jsonl.gz', 'rt')]
cand = [p for p in P if '[approx: polybeam' in (p.get('name') or '') and p.get('bbox')]
cand.sort(key=lambda p: -np.prod(np.maximum(np.array(p['bbox'][3:]) - np.array(p['bbox'][:3]), 1.0)))
tgt = cand[int(sys.argv[2]) if len(sys.argv) > 2 else 0]
bb = np.array(tgt['bbox']); base = tgt['name'].split(' [')[0]
# deployed product of the same part: same profile name, bbox inside the patched bbox, largest overlap
best = None
for d in D:
    if (d.get('name') or '').split(' [')[0] != base or not d.get('bbox'): continue
    db = np.array(d['bbox']); lo = np.maximum(db[:3], bb[:3]); hi = np.minimum(db[3:], bb[3:])
    ov = np.prod(np.maximum(hi - lo, 0)); vol = np.prod(np.maximum(db[3:] - db[:3], 1e-6))
    if ov / vol > 0.9 and (best is None or ov > best[0]): best = (ov, d)
print(json.dumps({'patched_root': tgt['i'], 'name': tgt['name'][:120], 'bbox': tgt['bbox'], 'deployed_root': best[1]['i'] if best else None,
                  'deployed_bbox': best[1]['bbox'] if best else None, 'patched_volume': tgt.get('volume'), 'deployed_volume': best[1].get('volume') if best else None}))
m = max(bb[3:] - bb[:3]) * 0.15 + 50
subprocess.run(['/opt/conv/env/bin/python', 'render_closeup.py', f'proof/{a}_jfix2.stp', f'proof/{a}_jfix2.parts.jsonl.gz', f'report/renders/{a}_polybeam_patched.png',
                '--root', str(tgt['i']), '--margin', str(m), '--title', f'{a} PATCHED (P5 polybeam along full polyline)'])
if best:
    # same window: deployed target bbox is smaller; render around the patched bbox by passing the deployed root and a margin covering the patched bbox
    dm = float(max(np.max(np.abs(np.array(best[1]['bbox'][:3]) - bb[:3])), np.max(np.abs(np.array(best[1]['bbox'][3:]) - bb[3:])))) + m
    subprocess.run(['/opt/conv/env/bin/python', 'render_closeup.py', f'out/{i}.i.stp', f'det/{i}.i.step_parts.jsonl.gz', f'report/renders/{a}_polybeam_deployed.png',
                    '--root', str(best[1]['i']), '--margin', str(dm), '--title', f'{a} DEPLOYED code i (polybeam = first segment only)'])
