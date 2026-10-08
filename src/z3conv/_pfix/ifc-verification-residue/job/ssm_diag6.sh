#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
cat > $W/diag/run6.sh <<'EOS'
W=/work/agentwork/ifc-verification-residue; P=/opt/conv/env/bin/python
timeout 1200 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/6f3ceef9bdcb1a56.bin 3ba3WXXxr7ZORBCV0kgw5D 1zVeLVTnz5cf0on7n7LpQl > $W/diag/far6_6f3c.jsonl 2> /dev/null
timeout 1200 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/7b35850cd279e675.bin 3JWeKhYjP529ZEqNLL7CXE 2_TkAlvfbCmvMQlufSg7JC > $W/diag/far6_7b35.jsonl 2> /dev/null
echo done > $W/diag/far6.done
aws s3 cp --quiet --recursive $W/diag/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/diag/ --exclude 'far2files/*' --exclude '*.ifc'
EOS
rm -f $W/diag/far6.done
setsid nohup bash $W/diag/run6.sh > /dev/null 2>&1 < /dev/null &
echo started
