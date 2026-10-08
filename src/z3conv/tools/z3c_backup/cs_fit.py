import json
d = json.load(open('/tmp/z3c/conv_status.json'))
B = [b for b in d['utilization']['boxes'] if b['cpus'] == 64]


def fit(ys):
    # least squares y = a*ifc + b*sds2 (no intercept), 2x2 normal equations
    s11 = s12 = s22 = t1 = t2 = 0.0
    for b, y in zip(B, ys):
        i = b['jobs'].get('ifc', 0); s = b['jobs'].get('sds2', 0)
        s11 += i * i; s12 += i * s; s22 += s * s; t1 += i * y; t2 += s * y
    det = s11 * s22 - s12 * s12
    return (t1 * s22 - t2 * s12) / det, (s11 * t2 - s12 * t1) / det


a, b = fit([x['reserved_gb'] for x in B])
print(f'reserved per job: ifc {a:.1f} GB, sds2 {b:.1f} GB')
a2, b2 = fit([x['mem_total_gb'] - x['mem_avail_gb'] - 10 for x in B])
print(f'used per job:     ifc {a2:.1f} GB, sds2 {b2:.1f} GB  (10 GB/box base)')
print('ifc jobs', sum(x['jobs'].get('ifc', 0) for x in d['utilization']['boxes']), 'sds2 jobs', sum(x['jobs'].get('sds2', 0) for x in d['utilization']['boxes']))
cap = 495 * 2.5
print(f'cap per 64-vCPU box at factor 2.5: {cap:.0f} GB -> IFC-only jobs at {a:.1f} GB reserved each: {cap / a:.0f} per box (slots 22)')
print(f'real: (495*0.95 - growth<=74) / {a2:.1f} GB used each = {(495 * 0.95 - 74) / max(a2, 1):.0f}..{495 * 0.95 / max(a2, 1):.0f} per box')
ok = [(x['host'][:16], x['gate']) for x in B]
print('gate ok_mem false:', sum(1 for _, g in ok if not g.get('ok_mem')), 'ok_cpu false:', sum(1 for _, g in ok if not g.get('ok_cpu')), 'of', len(ok))
a3, b3 = fit([x['load'] for x in B])
print(f'load per job:     ifc {a3:.2f}, sds2 {b3:.2f}  -> 22 IFC jobs ~ load {22 * a3:.0f} (assist cap 57.6, primary 60.8)')
