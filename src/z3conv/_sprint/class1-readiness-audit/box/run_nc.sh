cd /work/agentwork/class1-readiness-audit
for f in ncslot.py nc_find.json; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/$f job/; done
timeout 900 /opt/conv/env/bin/python job/ncslot.py job/nc_find.json ncslot.json 2>&1 | tail -3
