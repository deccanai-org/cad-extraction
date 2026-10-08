set -e
mkdir -p /work/agentwork/class1-readiness-audit && cd /work/agentwork/class1-readiness-audit
aws s3 cp --recursive --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/ ./job/
mkdir -p kit_k && aws s3 cp --recursive --only-show-errors --exclude 'fixes/*' --exclude 'v2/*' s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit_k/
/opt/conv/env/bin/python job/audit_patch.py kit_k
md5sum kit_k/db1bolts.py kit_k/db1bolts2.py kit_k/worker.py | cut -c1-12
grep -c DB1_AUDIT_DUMP kit_k/db1step.py
setsid nohup /opt/conv/env/bin/python job/aud.py kit_k k job/ids.json 12 > aud_k.log 2>&1 < /dev/null &
echo started $!
