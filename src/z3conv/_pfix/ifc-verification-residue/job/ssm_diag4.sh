#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/diag_far2.py $W/job/diag_far2.py
cd $W
P=/opt/conv/env/bin/python
export DIAG_OUT=$W/diag/far2files
timeout 250 $P $W/job/diag_far2.py $W/job/ifc2step6_dev3.py $W/in/4f6b8e2e96937507.bin 0Dcno5GC10KvAeo5hL2xEF 20pMG6xcT4PxReeWzIKuVz > $W/diag/far4_4f6b.jsonl 2> $W/diag/far4_4f6b.err
timeout 200 $P $W/job/diag_far2.py $W/job/ifc2step6_dev3.py $W/in/700b4c5c15d6f19e.bin 2QSNLZlfP8M8PeX2HhRG2E > $W/diag/far4_700b.jsonl 2> $W/diag/far4_700b.err
cat $W/diag/far4_*.jsonl; grep -v "zero norm" $W/diag/far4_*.err | tail -5
