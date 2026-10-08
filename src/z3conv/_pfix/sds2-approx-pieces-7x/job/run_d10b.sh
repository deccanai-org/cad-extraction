W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in getjob4.py d10b.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/d10b.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 2; echo started
