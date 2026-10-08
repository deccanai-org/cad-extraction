W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in dirs_conv.txt convb.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/convb.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 5; echo started; ps aux | grep sds2_to_step | grep base553 | grep -v grep | wc -l; free -g | head -2
