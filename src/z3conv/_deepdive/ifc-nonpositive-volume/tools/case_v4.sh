#!/bin/bash
# case_v4.sh ID_PREFIX : fetch one model, repair with the final lumpsplit, grade before/after, per-root regression
T=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/tools
cd /Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/data
P=$1; d=c${P:0:6}
$T/fetch_case.sh $P > /dev/null 2>&1
python3 $T/step_lumps2.py $d/out.stp $d/lumps2.jsonl > /dev/null
python3 $T/split_lumps_step.py $d/out.stp $d/split4.stp > $d/split4.stats
[ -f $d/occ_roots.jsonl ] || { $T/run_v.sh $d out > /dev/null; cp $d/occ_out.jsonl $d/occ_roots.jsonl; }
$T/run_v.sh $d split4
echo "   $(cat $d/split4.stats)"
python3 $T/regress.py split4 $d | head -1
