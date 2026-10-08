W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/run_diag3.sh $W/stage/run_diag3.sh
setsid nohup bash $W/stage/run_diag3.sh > $W/out/diag3.log 2>&1 < /dev/null &
sleep 2; echo launched; pgrep -f run_diag3.sh
