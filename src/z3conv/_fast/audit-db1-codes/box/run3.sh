#!/bin/bash
# run3.sh: patch proof - deployed j vs j + builder patches on the 7.1-7.4x models and the catalog-crash model (4 decoders)
cd /work/agentwork/audit-db1-codes
bash mkkits.sh > logs/mkkits.log 2>&1
IDS=$(/opt/conv/env/bin/python -c "
import json; e=json.load(open('state/engines.json')); print(','.join(sorted(i[:12] for i,v in e.items() if v and 7.1<=float(v)<7.5)+['7c68f0c9874e']))")
echo "$IDS" > logs/run3_ids.txt
bash phase.sh decode jfix_audit,j_audit 4 $IDS
