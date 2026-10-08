W=/work/agentwork/sds2-approx-pieces-7x
cd $W; aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/d7b.sh $W/d7b.sh
setsid nohup bash $W/d7b.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 2; echo started; ps aux | grep d7b | grep -v grep | head -3
