W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in conv_skip.sh convr.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/convr.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 8; ps -eo pid,args | grep -E "xargs|conv_all|convr" | grep sds2-approx | grep -v grep | cut -c1-150
