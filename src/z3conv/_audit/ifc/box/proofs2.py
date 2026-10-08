#!/usr/bin/env python3
"""IFC audit proof (read-only): a model whose s6 re-run the worker recorded as `readback_fail` (the v5 STEP was kept by
best-of, the v6 STEP was never uploaded). Re-convert it with the deployed ifc2step6 6.0.1 and run the deployed step_check.py
on the output exactly as the worker does, polling the tree RSS. Output: proofs2.json in the audit prefix."""
import os, sys, json, gzip, time, subprocess, collections
import boto3
from botocore.config import Config

B = 'bim-proprietary-data'; OUTK = 'cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc'
W = '/work/agentwork/audit-ifc'; P = os.path.join(W, 'proofs2'); os.makedirs(P, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 10, 'mode': 'standard'}))
cont = {json.loads(l)['id']: json.loads(l) for l in gzip.open(os.path.join(W, 'contents_ifc.jsonl.gz'), 'rt')}
mid = next(k for k in cont if k.startswith(sys.argv[1] if len(sys.argv) > 1 else '7a75aa3213eaf457'))
kit = os.path.join(P, 'kit'); os.makedirs(kit, exist_ok=True)
for f in ('ifc2step6.py', 'step_check.py'):
    s3.download_file('annotationprod', f'cad-disk-extract/_control/z3conv/ifc/{f}', os.path.join(kit, f))
src = os.path.join(P, mid[:16] + '.ifc')
s3.download_file(B, cont[mid]['input_key'], src)


def tree_rss(root):
    kids = collections.defaultdict(list)
    for d in os.listdir('/proc'):
        if d.isdigit():
            try:
                pp = int(open(f'/proc/{d}/stat').read().rsplit(')', 1)[1].split()[1]); kids[pp].append(int(d))
            except Exception:
                pass
    tot = 0; st = [root]
    while st:
        x = st.pop(); st.extend(kids.get(x, []))
        try:
            for line in open(f'/proc/{x}/status'):
                if line.startswith('VmRSS:'):
                    tot += int(line.split()[1]) << 10
        except Exception:
            pass
    return tot


def run(cmd, log, limit_gb=150, timeout=4 * 3600):
    t0 = time.time(); peak = 0; killed = None
    with open(log, 'w') as lf:
        p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=dict(os.environ, DEFLECTION='0.005', ANG_DEFLECTION='0.6'))
        while p.poll() is None:
            r = tree_rss(p.pid); peak = max(peak, r)
            if r > (limit_gb << 30):
                killed = f'tree RSS > {limit_gb} GB'; subprocess.run(['pkill', '-9', '-P', str(p.pid)]); p.kill(); break
            if time.time() - t0 > timeout:
                killed = 'timeout'; subprocess.run(['pkill', '-9', '-P', str(p.pid)]); p.kill(); break
            time.sleep(2)
        p.wait()
    return {'rc': p.returncode, 'killed': killed, 'sec': round(time.time() - t0, 1), 'peak_tree_rss_gb': round(peak / 2**30, 2),
            'log_tail': open(log, errors='replace').read()[-1500:]}


out = {'id': mid, 'size': os.path.getsize(src)}
stp = os.path.join(P, 'out.step')
out['convert'] = run(['/opt/conv/env/bin/python', os.path.join(kit, 'ifc2step6.py'), src, stp, '--mode', 'hybrid', '--prec', '2', '--threads', '2'],
                     os.path.join(P, 'convert.log'))
out['step_bytes'] = os.path.getsize(stp) if os.path.exists(stp) else None
try:
    st = json.load(open(stp + '.stats.json'))
    out['stats'] = {k: st.get(k) for k in ('parts', 'levels', 'tags', 'verify', 'out_bytes', 'peak_rss_mb', 'total_sec')}
except Exception as e:
    out['stats_error'] = str(e)
json.dump(out, open(os.path.join(W, 'proofs2.json'), 'w'), indent=1, default=str); s3.upload_file(os.path.join(W, 'proofs2.json'), B, OUTK + '/proofs2.json')
if out['step_bytes']:
    chk = os.path.join(P, 'out.check.json')
    out['step_check'] = run(['/opt/conv/env/bin/python', os.path.join(kit, 'step_check.py'), stp, chk, '--png', stp + '.png', '--parts', os.path.join(P, 'parts.jsonl.gz')],
                            os.path.join(P, 'check.log'))
    try:
        v = json.load(open(chk))
        out['step_check']['result'] = {k: v.get(k) for k in ('read_status', 'roots', 'transferred', 'solids', 'invalid', 'nonpos_vol', 'faces', 'error', 'sec', 'render_ink')}
    except Exception as e:
        out['step_check']['result_error'] = str(e)
json.dump(out, open(os.path.join(W, 'proofs2.json'), 'w'), indent=1, default=str); s3.upload_file(os.path.join(W, 'proofs2.json'), B, OUTK + '/proofs2.json')
print('done', flush=True)
