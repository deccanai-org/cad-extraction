cd /work/agentwork/class1-readiness-audit
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/locate.py job/
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/ids2.json job/
setsid nohup /opt/conv/env/bin/python job/locate.py job/ids2.json 15 > locate.log 2>&1 < /dev/null &
echo started $!
