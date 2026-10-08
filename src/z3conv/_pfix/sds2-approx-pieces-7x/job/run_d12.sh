W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in d12.sh dirs_d12.txt; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/d12.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 2; echo started
