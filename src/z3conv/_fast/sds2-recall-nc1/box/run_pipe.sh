#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && for f in run_jobs.py conv_jobs.py aggregate.py pipeline.sh nc1_holes_check.py stepidx.py sds2_ifc_recall.py ifc_products.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/$f $f; done
chmod +x *.sh
setsid nohup bash $W/bg.sh pipe bash $W/pipeline.sh > /dev/null 2>&1 < /dev/null &
sleep 1; echo started; tail -2 logs/d12b.log
