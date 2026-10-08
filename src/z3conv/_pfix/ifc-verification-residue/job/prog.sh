#!/bin/bash
# prog.sh LABEL... : print progress of drive runs
for L in "$@"; do
AWS_PROFILE=bim aws s3 cp s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/$L/progress.json - 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('==', d['label'], 'n',d['n'], 'done',len(d['done']), 'running', d['running'], d.get('finished',''))
for k,v in d['done'].items():
    print(k, v.get('tag'), 'was', v.get('was_class'), (v.get('was') or [])[:3], '->', v.get('class'), v.get('reasons'), (v.get('issues') or [])[:6], [s['type']+':'+str(s['count']) for s in (v.get('standins') or [])], 'cov', v.get('coverage_members'), v.get('coverage_all'), 'MB', v.get('out_mb'), 'lv', v.get('levels'), 'inst', (v.get('instancing') or {}).get('instances'), 's', v.get('sec'), 'rss', v.get('peak_tree_rss_mb'), v.get('fail_reason') or '', (v.get('error') or '')[-300:])
"
done
