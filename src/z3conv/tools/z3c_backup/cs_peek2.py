import json
d = json.load(open('/tmp/z3c/conv_status.json'))
for k in ('final', 'eta', 'verification_complete', 'verify_active', 'class1_pending', 'utilization', 'totals', 'incidents'):
    print(k, json.dumps(d.get(k), default=str)[:2500])
