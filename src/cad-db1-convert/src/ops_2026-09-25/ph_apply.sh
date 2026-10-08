cd /opt/ph
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc
( while pgrep -f "pkg_posthoc_run.py apply" >/dev/null; do aws s3 cp --region ap-south-1 --quiet /opt/ph/apply.log $C/apply.log; sleep 60; done; aws s3 cp --region ap-south-1 --quiet /opt/ph/apply.log $C/apply.log ) &
for pass in 1 2 3; do
  PKG_SOURCES=db1 PKG_STATE=cad-disk-extract/_control/packaging/step_v1_db1_posthoc THREADS=64 PROJ_THREADS=16 python3 /opt/ph/pkg_posthoc_run.py apply >> /opt/ph/apply.log 2>&1 && break
  echo "pass $pass had errors; retrying" >> /opt/ph/apply.log; sleep 20
done
echo "APPLY-FINISHED $(date -u +%H:%M:%SZ)" >> /opt/ph/apply.log
sleep 5; aws s3 cp --region ap-south-1 --quiet /opt/ph/apply.log $C/apply.log
