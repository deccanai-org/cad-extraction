#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/nc1_holes_check.py nc1_holes_check.py.new && mv nc1_holes_check.py.new nc1_holes_check.py
tail -3 logs/d12b.log; tail -3 logs/pipe.log
