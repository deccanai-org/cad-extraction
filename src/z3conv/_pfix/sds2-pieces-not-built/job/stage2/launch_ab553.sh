W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/ab553.sh $W/stage/ab553.sh
PAR=8 setsid nohup bash $W/stage/ab553.sh > $W/out/ab553.log 2>&1 < /dev/null &
sleep 2; echo launched; pgrep -f ab553.sh
