cd /work/agentwork/class1-readiness-audit
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/maskscan.py job/
ls src/6b87b724b554*.db1 src/5a2284473e4e*.db1 src/c8d753af8630*.db1 2>&1 | head
timeout 300 /opt/conv/env/bin/python job/maskscan.py 5a2284473e4e,6b87b724b554,c8d753af8630 2>&1 | tail -35
