W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in cand9_brep.py cand9_to_step2.py convc.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/convc.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 8; echo started; cat $W/convc.log; ps aux | grep d7b | grep -v grep | wc -l
