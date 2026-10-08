#!/bin/bash
# run9.sh (3 procs): full patch set P1-P6 (kit jfix2 = deployed j + builder_patch.py) on 4 models -> decoder IFC -> ifc2step6 -> step_check
cd /work/agentwork/audit-db1-codes; mkdir -p proof
rm -rf kits/jfix2 kits/jfix2_audit2 dec/jfix2_audit2 proof/*_jfix2*; cp -a kits/j kits/jfix2; /opt/conv/env/bin/python builder_patch.py kits/jfix2 > logs/run9_patch.log 2>&1
/opt/conv/env/bin/python patch_audit2.py kits/jfix2 kits/jfix2_audit2 >> logs/run9_patch.log 2>&1
M="6872ea14ba0c,0632e878d57c,305be94d6a71,6eabb07e7145,fd302a00f03f,0bbac8fc66cc,6f0dcc7daa09"
RUNTAG=r9 bash phase.sh decode jfix2_audit2 3 $M
step() { id=$(ls src | grep "^$1" | head -1); id=${id%.db1}; o=proof/${1}_jfix2
  /opt/conv/ifc84/bin/python kits/common/ifc2step6.py dec/jfix2_audit2/$id.ifc $o.stp --mode hybrid --prec 2 --threads 2 > $o.step.log 2>&1
  /opt/conv/env/bin/python kits/common/step_check.py $o.stp $o.check.json --png $o.png --parts $o.parts.jsonl.gz --title "$1 jfix2 (P1-P6)" > $o.chk.log 2>&1
  echo "step $1 done" >> logs/run9.log; }
for x in ${M//,/ }; do step $x & done; wait
aws s3 cp proof/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-db1-codes/proof/ --recursive --only-show-errors --exclude "*.stp"
echo run9 done >> logs/run9.log
