#!/bin/bash
/opt/conv/env/bin/python - <<'PY'
import json, glob
for f in glob.glob('/opt/pkgpartial/logs/pkgp-1e9122c3d688cb14-*.json'):
    r = json.load(open(f))
    print(f.rsplit('/',1)[-1], r.get('status'), r.get('reason'))
    ap = r.get('apply') or {}
    for x in (ap.get('failed') or [])[:6]: print(' FAILED', json.dumps(x)[:400])
    v = r.get('verify') or {}
    print(' verify checks', v.get('checks'), 'examples', json.dumps(v.get('examples'))[:600])
PY
