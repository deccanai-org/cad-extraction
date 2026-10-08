#!/bin/bash
# variants.sh ID PID VARIANT... : mini IFC of one part (code-f IFC from runs/audit) -> ifc2step5 hybrid (0.8.4.post1) -> OCP check
cd /Users/dhiren/Downloads/Deccan/z3conv/_fast/audit-db1-codes
export PYTHONDONTWRITEBYTECODE=1
ID=$(grep "^$1" ids.txt); PID=$2; shift 2
G=$(python3 -c "
import json,gzip
pl=json.load(gzip.open('runs/audit/$ID.parts.json.gz','rt'))
print([r[5] for r in pl if r[0]==$PID][0])")
for v in "$@"; do
  o=mini/${ID:0:12}_${PID}_${v//,/-}
  if [ "$v" = "none" ]; then ./venv/bin/python tools/mini_ifc.py runs/audit/$ID.ifc $o.ifc $G > /dev/null
  else ./venv/bin/python tools/mini_ifc.py runs/audit/$ID.ifc $o.ifc $G --drop-cuts $v > /dev/null; fi
  ./venv/bin/python kit_f/ifc2step5.py $o.ifc $o.stp --mode hybrid --prec 2 --threads 1 > $o.log 2>&1
  echo "== ${ID:0:12} pid $PID drop=$v : $(./venv/bin/python tools/occ_check.py $o.stp --detail)"
done
