W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/ $W/stage/
rm -rf $W/smoke
PAR=8 setsid nohup bash $W/stage/ab.sh > $W/out/ab.log 2>&1 < /dev/null &
sleep 2; echo launched; ls $W/out/cls/*.json | wc -l
