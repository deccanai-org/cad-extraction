cd /opt/ph
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc
aws s3 cp --region ap-south-1 --quiet $C/empty_step.py /opt/ph/empty_step.py
sed -i 's/^os.environ.setdefault("AWS_PROFILE", "bim")$/os.environ.pop("AWS_PROFILE", None)/' /opt/ph/refresh_packaged.py
grep -n 'AWS_PROFILE' /opt/ph/refresh_packaged.py > /opt/ph/refresh_dry.log
THREADS=64 python3 /opt/ph/refresh_packaged.py >> /opt/ph/refresh_dry.log 2>&1; echo "refresh dry rc=$?" >> /opt/ph/refresh_dry.log
python3 /opt/ph/empty_step.py plan > /opt/ph/empty_plan.log 2>&1; echo "empty plan rc=$?" >> /opt/ph/empty_plan.log
for f in refresh_dry.log empty_plan.log; do aws s3 cp --region ap-south-1 --quiet /opt/ph/$f $C/$f; done
echo STAGE-B-DONE > /opt/ph/stage_b.done; aws s3 cp --region ap-south-1 --quiet /opt/ph/stage_b.done $C/stage_b.done
