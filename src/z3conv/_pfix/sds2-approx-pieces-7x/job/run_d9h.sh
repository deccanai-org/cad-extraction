W=/work/agentwork/sds2-approx-pieces-7x
cd $W; aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/d9h.sh $W/d9h.sh
setsid nohup bash $W/d9h.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 2; echo started
