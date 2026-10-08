#!/bin/bash
# Mac monitor: every 60 s fetch the small status JSON, print newly finished / failed tasks (not fetch / clean)
SEEN=/tmp/svb_seen.txt; touch $SEEN
while true; do
  AWS_PROFILE=bim aws s3 cp --only-show-errors s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/status_main.json /tmp/svb_mon.json 2>/dev/null || { sleep 60; continue; }
  python3 - <<'PY'
import json
d = json.load(open('/tmp/svb_mon.json'))
seen = set(open('/tmp/svb_seen.txt').read().split())
new = []
for n, v in d['tasks'].items():
    if v['state'] in ('done', 'failed', 'skipped') and n not in seen:
        seen.add(n)
        if not n.startswith(('fetch', 'clean')) or v['state'] != 'done':
            new.append(f"{v['state']} {n} wall {v.get('wall_sec')} cpu {v.get('cpu_sec')} rss {v.get('max_rss_mb')} rc {v.get('rc')}")
open('/tmp/svb_seen.txt', 'w').write('\n'.join(sorted(seen)))
import collections
c = collections.Counter(v['state'] for v in d['tasks'].values())
if new:
    print(d['updated'], dict(c), 'load', d['box'].get('load', [''])[0], '|', ' ; '.join(new), flush=True)
if d.get('final'):
    print('QUEUE FINISHED', dict(c), flush=True)
PY
  python3 -c "import json,sys; sys.exit(0 if json.load(open('/tmp/svb_mon.json')).get('final') else 1)" && break
  sleep 60
done
