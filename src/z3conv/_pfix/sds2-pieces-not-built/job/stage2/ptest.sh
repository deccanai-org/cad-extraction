W=/work/agentwork/sds2-pieces-not-built; cd $W
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
for f in project_all.py project_one.py pfetch.py rows_test.json fetch.py; do aws s3 cp --quiet $C/$f $W/stage/$f; done
timeout 900 /opt/conv/env/bin/python $W/stage/project_all.py $W/stage/rows_test.json 4 2>&1 | tail
for d in $W/proj/*/; do echo "== $d"; cat $d/fetch.log | tail -2; tail -2 $d/v553.log; tail -2 $d/v553q.log; done
rm -f $W/out/PROJ_DONE
