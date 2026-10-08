#!/bin/bash
# READ-ONLY gate diagnosis (lead: find the binding admission gate). Only S3 GET / LIST of worker heartbeats + the admission factor;
# writes nothing. Per box and per worker process (data-3 and disk lanes): the last gate reading split into its sub-checks
#   real memory : avail - mem_floor*RAM - young growth >= exp
#   reservation : sum(max(exp, rss)) + exp <= RAM * factor
#   cpu         : load + recent starts' cores + job cores <= cap
# and which one blocks. Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/gate_diag.sh 200
export AWS_DEFAULT_REGION=ap-south-1
/opt/conv/env/bin/python - <<'PYEOF'
import json, time, collections
import boto3
s3 = boto3.client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
roots = {'d3': 'cad-disk-extract/zenitude-data-3/_state/conv', 'd4': 'cad-disk-extract/zentitude-data-4/_state/conv2'}
now = time.time()
def gj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception: return None
adm = gj(f"{roots['d3']}/admission.json") or {}
print('admission', adm)
H = collections.defaultdict(list)
for tag, st in roots.items():
    for p in ('ifc', 'db1', 'sds2', 'grade', 'verify', 'package'):
        for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=f'{st}/{p}/hosts/'):
            for o in pg.get('Contents', []):
                if now - o['LastModified'].timestamp() < 180:
                    d = gj(o['Key'])
                    if d: H[d['host']].append((tag, p, d))
fails = collections.Counter(); rows = []; byc = collections.Counter(); loadc = collections.defaultdict(list)
for host in sorted(H):
    for tag, p, d in H[host]:
        g = d.get('gate') or {}
        if not g or g.get('ok_mem') is None:
            continue
        t = (d.get('mem_total_gb') or 0); a = g.get('avail_gb') or 0; exp = g.get('exp_gb') or 0; gy = g.get('growth_gb') or 0
        resv = g.get('host_resv_gb') or 0
        fac = 3.0
        real_ok = a - 0.05 * t - gy >= exp
        resv_ok = resv + exp <= t * fac
        cpu_ok = bool(g.get('ok_cpu'))
        nrun = len(d.get('running') or []); sl = d.get('slots') or 0
        if g.get('ok_mem') and cpu_ok and g.get('ok_disk', True):
            why = 'slot_bound' if sl and nrun >= sl else 'admits'
        else:
            why = '+'.join([x for x, ok in (('real_mem', real_ok), ('resv_sum', resv_ok), ('cpu', cpu_ok), ('disk', g.get('ok_disk', True))) if not ok]) or 'other(psi/share/d3-reserve)'
        fails[(tag, why)] += 1
        cls_ = 'sg' if 'southeast' in host else ('32v' if (d.get('cpus') or 64) <= 32 else '64v')
        byc[(cls_, tag, why)] += 1; loadc[cls_].append((d.get('load') or 0) / (d.get('cpus') or 64))
        rows.append(f"{host[:22]} {tag}:{p:6} run {len(d.get('running') or []):2}/{d.get('slots')} load {g.get('load')}/{g.get('cap_cpu')} rc {g.get('recent_cores')} "
                    f"avail {a} growth {gy} exp {exp} resv {resv}/{round(t*fac)} -> {why}"
                    + (f" d3res {g.get('d3_reserved_gb')}GB/{g.get('d3_reserved_cores')}c" if g.get('yield_data3') else ''))
print('blocking checks:', dict(fails))
for c_ in sorted({k[0] for k in byc}):
    print(f"  class {c_}: load/vCPU avg {sum(loadc[c_]) / max(1, len(loadc[c_])):.2f}; " + ', '.join(f'{t}:{w}={n}' for (cc, t, w), n in sorted(byc.items()) if cc == c_))
print('\n'.join(rows[:80]))
PYEOF
