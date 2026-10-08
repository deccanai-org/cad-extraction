#!/bin/bash
cd /work/agentwork/audit-sds2-v5x
/opt/conv/env/bin/python - <<'PY'
import json, gzip, collections, re
rows = [json.loads(l) for l in gzip.open('s3/conv/index.jsonl.gz', 'rt') if l.strip()]
s = [r for r in rows if r['pipeline'] == 'sds2']
print('sds2 rows', len(s), collections.Counter((r.get('reused'), r.get('status')) for r in s).most_common(12))
alt = [r for r in s if r.get('alternative')]
sup = [r for r in s if r.get('supersedes') and r['supersedes'].get('class') is not None]
print('reused kept over data-3 conversion (alternative):', len(alt), collections.Counter((r['class'], r['alternative'].get('class'), re.sub(r'-2026.*', '', str(r['alternative'].get('converter_code')))) for r in alt).most_common())
print('data-3 conversion superseded reused:', len(sup), collections.Counter((r['supersedes'].get('class'), r['class'], r.get('converter')) for r in sup).most_common())
for r in alt[:30]:
    print('  ALT', r['id'][:12], 'reused class', r['class'], 'n_iss', len(r['issues']) + len(r['standins']) + len(r['needs']), '| new', r['alternative'])
print(json.dumps({k: v for k, v in alt[0].items() if k not in ('paths',)}, default=str)[:1500] if alt else '')
rc = json.load(open('s3/sds2/jobs_reconvert.json')); print('jobs_reconvert', len(rc))
PY
