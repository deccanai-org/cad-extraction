import json, sys
d = json.load(open('/tmp/z3c/conv_status.json'))
print('updated', d.get('updated'))
print('top keys', list(d.keys())[:60])
p = d.get('packaging') or {}
print('packaging', json.dumps({k: v for k, v in p.items() if k not in ('jobs',)}, default=str)[:3000])
for k in ('pipelines', 'pipes', 'by_pipe', 'vpipes', 'fleet', 'admission', 'slots', 'load'):
    if k in d:
        print(k, json.dumps(d[k], default=str)[:4000])
