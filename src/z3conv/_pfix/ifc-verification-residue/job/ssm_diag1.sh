#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/diag_far.py $W/job/diag_far.py
cd $W
P=/opt/conv/env/bin/python
mkdir -p $W/diag
timeout 600 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/c13135ba64e2e8fd.bin 0_Aurq9PnFi99OUJ6HJXZq 0vFQuB_zv3NQvNavVsU3CF > $W/diag/far_c131.jsonl 2> $W/diag/far_c131.err
timeout 600 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/4f6b8e2e96937507.bin 0Dcno5GC10KvAeo5hL2xEF 20pMG6xcT4PxReeWzIKuVz > $W/diag/far_4f6b.jsonl 2> $W/diag/far_4f6b.err
timeout 600 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/700b4c5c15d6f19e.bin '2QSNLZlfP8M8PeX2HhRG2E' > $W/diag/far_700b.jsonl 2> $W/diag/far_700b.err
cat $W/diag/far_*.jsonl; tail -5 $W/diag/far_*.err
aws s3 cp --quiet --recursive $W/diag/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/diag/
