#!/bin/bash
# run2.sh: decoders (audit kits i/h + g, f, b0 on all models; intermediate kits on models <= 5 MB) -> bolt audit -> parts lost -> invalid solids
cd /work/agentwork/audit-db1-codes
rm -rf dec/i_audit dec/h_audit kits/i_audit kits/h_audit
/opt/conv/env/bin/python patch_audit.py kits/i kits/i_audit > logs/patch.log; /opt/conv/env/bin/python patch_audit.py kits/h kits/h_audit >> logs/patch.log
bash phase.sh decode i_audit,h_audit,g,f,b0 14
bash phase.sh audit_bolts i_audit
bash phase.sh audit_bolts h_audit
DEC_MAX_MB=5 bash phase.sh decode e,d,c2,c,b2,b1 14
bash phase.sh parts_lost
