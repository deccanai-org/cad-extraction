cd /work/agentwork/class1-readiness-audit
for f in profcheck.py profdb.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/$f job/; done
timeout 600 /opt/conv/env/bin/python job/profcheck.py k 2>&1 | tail -3
