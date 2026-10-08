#!/bin/bash
# Mac: summarize the box queue status (small JSON from S3)
AWS_PROFILE=bim aws s3 cp --only-show-errors s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/status_main.json /tmp/svb_status.json && python3 - <<'PY'
import json, collections
d = json.load(open('/tmp/svb_status.json'))
c = collections.Counter(v['state'] for v in d['tasks'].values())
print(d['updated'], 'elapsed', d['elapsed_sec'], 's final', d['final'], 'box', d['box'], dict(c))
for n, v in d['tasks'].items():
    if v['state'] in ('running',):
        print('  RUN ', n, v.get('started'))
    elif v['state'] in ('failed', 'skipped'):
        print('  ' + v['state'].upper(), n, v.get('rc'), v.get('why', ''))
done = [(n, v) for n, v in d['tasks'].items() if v['state'] == 'done' and not n.startswith(('fetch', 'clean'))]
for n, v in done[-40:]:
    print('  done', n, 'wall', v.get('wall_sec'), 'cpu', v.get('cpu_sec'), 'maxrss_mb', v.get('max_rss_mb'))
PY
