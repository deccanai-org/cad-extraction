W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in cand7_brep.py cand7_to_step2.py diag2.py d8.sh; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/d8.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 4; echo started; cat $W/d8.log; grep diag.py $W/diag_all_d8.sh
