#!/bin/bash
# run8.sh ID KIT: STEP proof of a patched decode: decoder IFC (dec/KIT/ID.ifc) -> ifc2step6 (as the worker: hybrid, prec 2, 4 threads) -> step_check
cd /work/agentwork/audit-db1-codes; mkdir -p proof
id=$(ls src | grep "^$1" | head -1); id=${id%.db1}; K=$2
until [ -f dec/$K/$id.json ]; do sleep 20; done
o=proof/${1}_$K
/opt/conv/ifc84/bin/python kits/common/ifc2step6.py dec/$K/$id.ifc $o.stp --mode hybrid --prec 2 --threads 4 > $o.step.log 2>&1
/opt/conv/env/bin/python kits/common/step_check.py $o.stp $o.check.json --png $o.png --parts $o.parts.jsonl.gz --title "$1 $K" > $o.chk.log 2>&1
aws s3 cp proof/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-db1-codes/proof/ --recursive --only-show-errors --exclude "*.stp"
echo done $1 $K >> logs/run8.log
