#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/sds2_ifc_recall.py sds2_ifc_recall.py.new && mv sds2_ifc_recall.py.new sds2_ifc_recall.py
cat > ifcB.sh <<'SH'
cd /work/agentwork/sds2-recall-nc1
mv out/ifc out/ifc_A_$(date +%H%M); mkdir -p out/ifc
/opt/conv/env/bin/python run_jobs.py --phase ifc --no-digest --workers 4 --tag ifcB
/opt/conv/env/bin/python aggregate.py > out/aggregate_interim.txt 2>&1
echo ifcB done
SH
setsid nohup bash $W/bg.sh ifcB bash $W/ifcB.sh > /dev/null 2>&1 < /dev/null &
sleep 1; echo started
