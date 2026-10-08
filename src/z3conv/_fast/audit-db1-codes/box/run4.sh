#!/bin/bash
# run4.sh (12 decoders): bolt audit v2 on every old-engine model: jfix_audit2 (deployed hole rule + P1-P3) then jfixr_audit2 (+P4)
cd /work/agentwork/audit-db1-codes
bash mkkits2.sh > logs/mkkits2.log 2>&1
OLD=$(/opt/conv/env/bin/python -c "
import json; e=json.load(open('state/engines.json')); print(','.join(sorted(i[:12] for i,v in e.items() if v in ('6.87','7.01','7.24','7.30'))))")
echo "$OLD" > logs/run4_ids.txt
bash phase.sh decode jfix_audit2,jfixr_audit2 12 $OLD
