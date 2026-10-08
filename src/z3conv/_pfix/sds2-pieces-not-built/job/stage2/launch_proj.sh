W=/work/agentwork/sds2-pieces-not-built; cd $W
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built
for f in project_all.py project_one.py pfetch.py pnb_rows_live.json fetch.py; do aws s3 cp --quiet $C/$f $W/stage/$f; done
setsid nohup /opt/conv/env/bin/python $W/stage/project_all.py $W/stage/pnb_rows_live.json 6 > $W/out/proj.log 2>&1 < /dev/null &
sleep 2; echo launched; pgrep -f project_all.py
