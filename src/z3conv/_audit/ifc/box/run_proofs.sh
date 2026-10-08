#!/bin/bash
cd /work/agentwork/audit-ifc
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-ifc/proofs.py proofs.py
cat > pjob.sh <<'J'
#!/bin/bash
cd /work/agentwork/audit-ifc
taskset -c 46-63 /opt/conv/env/bin/python proofs.py precision,hss,oom,absurd > proofs.log 2>&1
aws s3 cp --quiet proofs.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc/proofs.log
J
chmod +x pjob.sh; setsid nohup ./pjob.sh > pjob.out 2>&1 < /dev/null &
echo started $!
