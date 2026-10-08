import json, sys
out = {}; src = {}
order = sys.argv[2:]          # highest priority first
for f in reversed(order):
    P = json.load(open(f))
    for k, v in P.items():
        if v.get('projected') is not None or k not in out:
            out[k] = v; src[k] = f
for k in out: out[k]['_from'] = src[k]
json.dump(out, open(sys.argv[1], 'w'), indent=1)
import collections; print(sys.argv[1], collections.Counter(v.get('projected') for v in out.values()), collections.Counter(src.values()))
