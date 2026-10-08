W=/work/agentwork/sds2-pieces-not-built; cd $W
aws s3 cp --recursive --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-pieces-not-built/ $W/stage/
# stop my old A/B runners (only my own PIDs: the xargs of ab.sh / ab_v4.sh and their old-code 'b' conversions)
for p in $(pgrep -f "bash $W/stage/ab.sh") $(pgrep -f "bash $W/stage/ab_v4.sh"); do pkill -P $p xargs 2>/dev/null; kill $p 2>/dev/null; done
pkill -f "xargs -P 8 -L 1 bash -c run" ; pkill -f "xargs -P 4 -L 1 bash -c run"
for p in $(pgrep -f "$W/trees/b/decode/sds2_to_step.py"); do kill $p; done
sleep 2
# old-code b dirs without a result are removed (b2 replaces them)
for d in $W/ab/b/*/; do [ -f $d/rc.txt ] || rm -rf $d; done
echo "running a: $(pgrep -f "$W/trees/a/decode/sds2_to_step.py" | wc -l)"
PAR=10 setsid nohup bash $W/stage/ab2.sh > $W/out/ab2.log 2>&1 < /dev/null &
sleep 2; echo relaunched
