#!/bin/bash
# fetch_case.sh <id-prefix> : downloads source IFC (src.bin) and STEP (out.stp) of one npv model into data/c<prefix>/
set -e
export AWS_PROFILE=bim
D0=/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume/data
P=$1; R=$(ls $D0/res/*$P*.json 2>/dev/null | head -1)
[ -z "$R" ] && R=$(ls $D0/res/ifc-$P*.json | head -1)
D=$D0/c${P:0:6}; mkdir -p $D
IFS=$'\t' read IN STEPK < <(python3 -c "
import json,sys; r=json.load(open('$R'))
print(str(r.get('input_key'))+chr(9)+(r.get('step_key') or r.get('out_key')))")
if [ "$IN" = "None" ]; then IN=$(python3 -c "
import json; j=json.load(open('$D0/gjobs.json')); print([x for x in j if ('-'+'$P') in x['id']][0]['input_key'])"); fi
[ -f $D/src.bin ] || aws s3 cp --quiet "s3://bim-proprietary-data/$IN" $D/src.bin
[ -f $D/out.stp ] || aws s3 cp --quiet "s3://bim-proprietary-data/$STEPK" $D/out.stp
cp $R $D/result.json
ls -la $D
