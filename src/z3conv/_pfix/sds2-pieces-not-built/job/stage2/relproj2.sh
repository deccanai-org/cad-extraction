W=/work/agentwork/sds2-pieces-not-built; cd $W
for p in $(pgrep -f "stage/project_all.py"); do kill $p; done
sleep 1
for p in $(pgrep -f "stage/project_one.py") $(pgrep -f "stage/pfetch.py"); do kill $p 2>/dev/null; done
sleep 1
# results produced by the 1500-cap run before the restart stay valid (fetch and replay used the same cap); results of
# the short-lived 300-fetch / 1500-replay run are removed
for d in $W/proj/*/; do if [ -f $d/DONE ] && [ $(wc -l < $d/sids.txt) -lt 1499 ] && [ $(wc -l < $d/sids.txt) -eq 299 ]; then rm -rf $d; fi; done
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/project_all.py $W/stage/project_all.py
grep -c "'300'" $W/stage/project_all.py
setsid nohup /opt/conv/env/bin/python $W/stage/project_all.py $W/stage/pnb_rows_live.json 8 > $W/out/proj.log 2>&1 < /dev/null &
sleep 2; pgrep -f project_all.py; ls $W/proj | wc -l; ls $W/proj/*/DONE | wc -l
