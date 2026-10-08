W=/work/agentwork/sds2-pieces-not-built; cd $W
for p in $(pgrep -f "stage/project_all.py"); do kill $p; done
sleep 1
for p in $(pgrep -f "stage/project_one.py") $(pgrep -f "stage/pfetch.py"); do kill $p 2>/dev/null; done
sleep 1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/project_all.py $W/stage/project_all.py
setsid nohup /opt/conv/env/bin/python $W/stage/project_all.py $W/stage/pnb_rows_live.json 8 > $W/out/proj.log 2>&1 < /dev/null &
sleep 2; pgrep -f project_all.py; ls $W/proj | wc -l; ls $W/proj/*/DONE | wc -l
