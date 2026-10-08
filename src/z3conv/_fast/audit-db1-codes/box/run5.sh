#!/bin/bash
# run5.sh (6 decoders): parts written per code kit with bolts off (non-bolt parts are bolt-independent: f bolts vs no-bolts A/B = 0 lost)
cd /work/agentwork/audit-db1-codes
sleep 20
DB1_BOLTS=0 DEC_TAG=nb bash phase.sh decode b0,c,f,g,h,i,j,jfix 6
bash phase.sh parts_lost
