cd /work/agentwork/class1-readiness-audit
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/fieldscan.py job/
timeout 300 /opt/conv/env/bin/python job/fieldscan.py
