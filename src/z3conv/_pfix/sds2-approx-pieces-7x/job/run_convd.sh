W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in convd.sh dirs_conv2.txt; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/convd.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 2; echo started
