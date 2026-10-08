#!/bin/bash
# run6.sh (3 procs): decoder IFC of code i for the models whose deployed .i STEP holds L4-surface parts -> mini-part variants
cd /work/agentwork/audit-db1-codes
[ -d kits/i_audit ] || /opt/conv/env/bin/python patch_audit.py kits/i kits/i_audit
RUNTAG=r6 bash phase.sh decode i_audit 3 305be94d6a71,1a70f9f2afe4,748b957ceace,9cf26a05e061,bceea537cbda,c8d753af8630,f31a33fc6fae
RUNTAG=r6 bash phase.sh step_invalid 3
