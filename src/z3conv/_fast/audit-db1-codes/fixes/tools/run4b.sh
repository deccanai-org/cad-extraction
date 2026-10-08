#!/bin/bash
# run4b.sh (12 decoders): bolt audit v2 (audit dump on) on the old-engine models <= 9 MB (one copy of each repeated 7.24 job) + 7.30
cd /work/agentwork/audit-db1-codes
[ -d dec/jfix_stats ] || mv dec/jfix_audit2 dec/jfix_stats; rm -rf dec/jfixr_audit2
IDS=$(/opt/conv/env/bin/python -c "
import json, os
e=json.load(open('state/engines.json')); J={j['id']: j for j in json.load(open('state/all_jobs.json'))}
dup724={'14a172ca0af2','8bf0b1382da6','81603492ccb9','b88e66e4b457','ec92f6149806','88be5995e1e4','e6ec773c7179','ef37a14c7e42','ffd36bc29f2f','148a5d4883db','5b33936fcd1e','b3d488c0a0fd','27a9febf9f71'}
ids=[i[:12] for i,v in e.items() if v in ('6.87','7.01','7.24','7.30') and (J[i]['size'] <= 9e6 or i[:12] in ('7c82c44be6c7',)) and i[:12] not in dup724]
print(','.join(sorted(ids)))")
echo "$IDS" > logs/run4b_ids.txt
RUNTAG=r4b bash phase.sh decode jfix_audit2,jfixr_audit2 12 $IDS
RUNTAG=r4b bash phase.sh audit_bolts jfix_audit2
RUNTAG=r4b2 bash phase.sh audit_bolts jfixr_audit2
RUNTAG=r4b bash phase.sh dupholes jfix_audit2
RUNTAG=r4b2 bash phase.sh dupholes jfixr_audit2
RUNTAG=r4b bash phase.sh nc1_check
