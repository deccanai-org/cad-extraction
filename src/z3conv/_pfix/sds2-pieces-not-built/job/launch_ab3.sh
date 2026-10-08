W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/ab3.sh $W/stage/ab3.sh
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/trees3.tgz $W/stage/trees3.tgz
setsid nohup bash $W/stage/ab3.sh > $W/out/ab3.log 2>&1 < /dev/null &
sleep 1; echo launched
for d in $W/ab/*/*/; do [ -f $d/rc.txt ] && echo "$(basename $(dirname $d))/$(basename $d) $(cat $d/rc.txt)"; done
cat $W/out/ab2_jobs.txt | wc -l
