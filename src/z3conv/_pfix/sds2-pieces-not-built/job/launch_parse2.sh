W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/ $W/stage/
setsid nohup bash $W/stage/run_parse2.sh > $W/out/parse2.log 2>&1 < /dev/null &
echo launched
