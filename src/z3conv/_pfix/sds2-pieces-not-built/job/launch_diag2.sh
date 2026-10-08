W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/ $W/stage/
setsid nohup bash $W/stage/run_diag2.sh > $W/out/diag2.log 2>&1 < /dev/null &
sleep 1; echo launched; cat $W/out/slot_layouts.txt 2>/dev/null; cat $W/out/ab_queue.txt 2>/dev/null | wc -l
