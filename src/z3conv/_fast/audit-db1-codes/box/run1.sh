#!/bin/bash
# run1.sh: fetch (cached) -> relation tables (6 procs) || decoders of every code (14 procs) -> bolt audit -> parts lost
cd /work/agentwork/audit-db1-codes
bash phase.sh fetch
bash phase.sh rel10 &
bash phase.sh decode i_audit,h_audit,i,h,g,f,e,d,c2,c,b2,b1,b0 14
wait
bash phase.sh audit_bolts i_audit
bash phase.sh audit_bolts h_audit
bash phase.sh parts_lost
