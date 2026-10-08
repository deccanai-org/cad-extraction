#!/bin/bash
T=$1
until [ "$(date -u +%H%M)" -ge "$T" ]; do sleep 30; done
AWS_PROFILE=annotationprod-publish aws s3 ls s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/converter.json >/dev/null 2>&1 && echo SSO-OK || echo SSO-EXPIRED
AWS_PROFILE=bim aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv_status.json - | python3 -c "
import json,sys; S=json.load(sys.stdin)
print(S['updated'], 'final', S.get('final'), 'revs', S.get('final_revisions'))
for p,e in (S.get('eta') or {}).items():
    if isinstance(e,dict): print(p, {k:e.get(k) for k in ('fresh_open','fresh_eta_hours','rerun_open','rerun_eta_hours','long_tail') if k in e})
print('incidents', S.get('incidents'))
" 2>&1 | grep -v -i warn
AWS_PROFILE=bim aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/final/auto_status.json - 2>/dev/null | head -c 600; echo
python3 /tmp/z3c/mon2.py 2>&1 | grep -v -i warn | tail -1
