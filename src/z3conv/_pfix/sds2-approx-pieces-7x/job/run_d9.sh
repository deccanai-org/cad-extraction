W=/work/agentwork/sds2-approx-pieces-7x
cd $W; for f in cand8_brep.py cand8_to_step2.py d9.sh dirs_fixer.txt; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-approx-pieces-7x/$f $W/$f; done
setsid nohup bash $W/d9.sh > /dev/null 2>&1 < /dev/null &
disown; sleep 6; echo started; cat $W/d9.log; ps aux | grep -c "diag.py.d8"; ps aux | grep -c "diag.py.d9"
