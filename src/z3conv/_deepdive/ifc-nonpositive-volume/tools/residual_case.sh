#!/bin/bash
T=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/tools
cd /Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/data
P=$1; d=c${P:0:6}
$T/fetch_case.sh $P > /dev/null 2>&1
python3 $T/step_lumps2.py $d/out.stp $d/lumps2.jsonl > /dev/null
python3 $T/split_lumps_step.py $d/out.stp $d/split4.stp > $d/split2.stats
rm -f $d/occ_split4.jsonl $d/chk_split4.json
$T/run_after.sh $d > /dev/null
python3 $T/residual.py $d > $d/residual.txt
echo "== $d $(cat $d/split2.stats)"; tail -1 $d/residual.txt
