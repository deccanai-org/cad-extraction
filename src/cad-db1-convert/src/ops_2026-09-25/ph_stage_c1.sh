cd /opt/ph
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc
aws s3 cp --region ap-south-1 --quiet $C/verify_dataset.py /opt/ph/verify_dataset.py
up() { for f in "$@"; do aws s3 cp --region ap-south-1 --quiet /opt/ph/$f $C/$f; done; }
THREADS=64 python3 /opt/ph/refresh_packaged.py --apply > /opt/ph/refresh_apply.log 2>&1; echo "refresh apply rc=$?" >> /opt/ph/refresh_apply.log; up refresh_apply.log
rm -f /opt/ph/verify.log
for i in $(seq 0 15); do (VERIFY_SHARD=$i/16 python3 /opt/ph/verify_dataset.py >> /opt/ph/verify.log 2>&1 &); done
sleep 20; while pgrep -f verify_dataset.py >/dev/null; do sleep 20; done; up verify.log
echo STAGE-C1-DONE > /opt/ph/stage_c1.done; up stage_c1.done
