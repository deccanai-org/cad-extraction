export SRC=db1 FIRST=0 LAST=13 N=30
S=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1
mkdir -p /opt/pkg && cd /opt/pkg
aws s3 cp --region ap-south-1 --quiet $S/pkg_step.py /opt/pkg/pkg_step.py
cat > /opt/pkg/db1_pass.sh <<EOF
#!/bin/bash
cd /opt/pkg
PKG_SOURCES=db1 THREADS=96 python3 /opt/pkg/pkg_step.py plan > /opt/pkg/db1_plan.log 2>&1
aws s3 cp --region ap-south-1 --quiet /opt/pkg/db1_plan.log $S/plan.log
date -u +%FT%TZ | aws s3 cp --region ap-south-1 --quiet - $S/plan_ready
for pass in 1 2 3; do
  for i in \$(seq $FIRST $LAST); do (PKG_SOURCES=db1 PKG_SHARD=\$i/$N THREADS=48 PROJ_THREADS=1 python3 /opt/pkg/pkg_step.py apply >> /opt/pkg/db1_shard_\$i.log 2>&1 &); done
  sleep 20; while pgrep -f "pkg_step.py apply" >/dev/null; do sleep 30; done
  tail -q -n 1 /opt/pkg/db1_shard_*.log | grep -q error || break
done
echo DB1PASS_DONE > /opt/pkg/db1_done.txt; aws s3 cp --region ap-south-1 --quiet /opt/pkg/db1_done.txt $S/done_\$(hostname).txt
EOF
chmod +x /opt/pkg/db1_pass.sh; (nohup /opt/pkg/db1_pass.sh > /opt/pkg/db1_pass.out 2>&1 &); sleep 2; pgrep -fc db1_pass.sh
