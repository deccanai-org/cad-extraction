cd /work/agentwork/class1-readiness-audit
for f in fullconv.py ids_full.json; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/$f job/; done
setsid nohup /opt/conv/env/bin/python job/fullconv.py kit_k4e full_k4e job/ids_full.json 4 > full_k4e.log 2>&1 < /dev/null &
echo started $!
