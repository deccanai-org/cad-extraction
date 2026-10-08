#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/diag_far2.py $W/job/diag_far2.py
cd $W
P=/opt/conv/env/bin/python
export DIAG_OUT=$W/diag/far2files DIAG_Q=0
cat > $W/diag/run5.sh <<'EOS'
W=/work/agentwork/ifc-verification-residue; P=/opt/conv/env/bin/python
DIAG_SRC=kernel timeout 900 $P $W/job/diag_far2.py $W/job/ifc2step6_dev3.py $W/in/c13135ba64e2e8fd.bin 0_Aurq9PnFi99OUJ6HJXZq > $W/diag/far5_c131.jsonl 2> /dev/null
DIAG_SRC=kernel timeout 900 $P $W/job/diag_far2.py $W/job/ifc2step6_dev3.py $W/in/6f3ceef9bdcb1a56.bin 1zVeLVTnz5cf0on7n7LpQl > $W/diag/far5_6f3c_k.jsonl 2> /dev/null
DIAG_SRC=tc timeout 900 $P $W/job/diag_far2.py $W/job/ifc2step6_dev3.py $W/in/6f3ceef9bdcb1a56.bin 3ba3WXXxr7ZORBCV0kgw5D > $W/diag/far5_6f3c_t.jsonl 2> /dev/null
DIAG_SRC=kernel timeout 900 $P $W/job/diag_far2.py $W/job/ifc2step6_dev3.py $W/in/7b35850cd279e675.bin 3JWeKhYjP529ZEqNLL7CXE 2_TkAlvfbCmvMQlufSg7JC > $W/diag/far5_7b35.jsonl 2> /dev/null
echo done > $W/diag/far5.done
aws s3 cp --quiet --recursive $W/diag/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/diag/ --exclude 'far2files/*'
EOS
rm -f $W/diag/far5.done
DIAG_OUT=$W/diag/far2files DIAG_Q=0 setsid nohup bash $W/diag/run5.sh > /dev/null 2>&1 < /dev/null &
echo started
