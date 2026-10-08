#!/bin/bash
W=/work/agentwork/sds2-approx-pieces-7x
mkdir -p $W && cd $W
for f in cand6_brep.py cand6_to_step2.py mkvar553.sh d7.sh d7b.sh p1.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
chmod +x *.sh
S=${1:-d7.sh}
setsid nohup bash $W/$S > /dev/null 2>&1 < /dev/null &
disown
sleep 3; echo started $S
