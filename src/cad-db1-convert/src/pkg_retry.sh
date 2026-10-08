# after the running shard processes exit, re-run the same shards with the latest packager until clean
cat > /opt/pkg/retry_loop.sh <<EOF
#!/bin/bash
S=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_\$SRC
while pgrep -f "pkg_step.py apply" >/dev/null; do sleep 30; done
for pass in 1 2 3; do
  aws s3 cp --region ap-south-1 --quiet \$S/pkg_step.py /opt/pkg/pkg_step.py
  for i in \$(seq \$FIRST \$LAST); do
    (PKG_SOURCES=\$SRC PKG_SHARD=\$i/\$N THREADS=48 PROJ_THREADS=1 python3 /opt/pkg/pkg_step.py apply >> /opt/pkg/shard_\$i.log 2>&1 &)
  done
  sleep 20; while pgrep -f "pkg_step.py apply" >/dev/null; do sleep 30; done
  if ! tail -q -n 1 /opt/pkg/shard_*.log | grep -q "error"; then echo "pass \$pass clean" >> /opt/pkg/retry.log; break; fi
  echo "pass \$pass had errors" >> /opt/pkg/retry.log
done
echo ALLDONE >> /opt/pkg/retry.log
aws s3 cp --region ap-south-1 --quiet /opt/pkg/retry.log \$S/retry_\$(hostname).log
EOF
chmod +x /opt/pkg/retry_loop.sh
(SRC=$SRC FIRST=$FIRST LAST=$LAST N=$N nohup /opt/pkg/retry_loop.sh > /opt/pkg/retry_loop.out 2>&1 &)
sleep 2; pgrep -fc retry_loop.sh
