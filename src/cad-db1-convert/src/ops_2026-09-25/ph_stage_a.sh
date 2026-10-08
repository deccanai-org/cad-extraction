cd /opt/ph
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc
until grep -q APPLY-FINISHED /opt/ph/apply.log 2>/dev/null; do sleep 15; done
for f in refresh_packaged.py dedup_step.py verify_dataset.py; do aws s3 cp --region ap-south-1 --quiet $C/$f /opt/ph/$f; done
cp /opt/ph/pkg_posthoc_run.py /opt/ph/pkg_step.py
THREADS=64 python3 /opt/ph/refresh_packaged.py > /opt/ph/refresh_dry.log 2>&1; echo "refresh dry rc=$?" >> /opt/ph/refresh_dry.log
python3 /opt/ph/dedup_step.py plan > /opt/ph/dedup_plan.log 2>&1; echo "dedup plan rc=$?" >> /opt/ph/dedup_plan.log
for f in refresh_dry.log dedup_plan.log; do aws s3 cp --region ap-south-1 --quiet /opt/ph/$f $C/$f; done
echo STAGE-A-DONE > /opt/ph/stage_a.done; aws s3 cp --region ap-south-1 --quiet /opt/ph/stage_a.done $C/stage_a.done
