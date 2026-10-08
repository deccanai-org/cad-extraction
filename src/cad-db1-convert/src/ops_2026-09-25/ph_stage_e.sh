cd /opt/ph
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc
A="aws s3 cp --region ap-south-1 --quiet"
up() { for f in "$@"; do $A /opt/ph/$f $C/$f; done; }
until [ -f /opt/ph/stage_d.done ]; do sleep 20; done
# user-approved 2026-09-25: remove header-only STEP, collapse identical STEP, remove the empty probe package
python3 /opt/ph/empty_step.py plan > /opt/ph/empty_plan2.log 2>&1; echo "empty plan rc=$?" >> /opt/ph/empty_plan2.log; up empty_plan2.log
python3 /opt/ph/empty_step.py apply > /opt/ph/empty_apply.log 2>&1; echo "empty apply rc=$?" >> /opt/ph/empty_apply.log; up empty_apply.log
python3 /opt/ph/dedup_step.py plan > /opt/ph/dedup_plan3.log 2>&1; echo "dedup plan rc=$?" >> /opt/ph/dedup_plan3.log; up dedup_plan3.log
python3 /opt/ph/dedup_step.py apply > /opt/ph/dedup_apply.log 2>&1; echo "dedup apply rc=$?" >> /opt/ph/dedup_apply.log; up dedup_apply.log
P=cad-disk-extract/dataset/main/2d/Disk-1___probe/
aws s3 ls --region ap-south-1 --recursive s3://annotationprod/$P > /opt/ph/probe_pkg.log
if [ "$(wc -l < /opt/ph/probe_pkg.log)" -eq 1 ] && grep -q "project.json" /opt/ph/probe_pkg.log; then
  $A s3://annotationprod/${P}project.json $C/removed/Disk-1___probe.project.json
  aws s3 rm --region ap-south-1 s3://annotationprod/${P}project.json >> /opt/ph/probe_pkg.log 2>&1 && echo "probe package removed" >> /opt/ph/probe_pkg.log
else echo "probe package NOT removed: unexpected contents" >> /opt/ph/probe_pkg.log; fi
up probe_pkg.log
rm -f /opt/ph/verify.log
for i in $(seq 0 15); do (VERIFY_SHARD=$i/16 python3 /opt/ph/verify_dataset.py >> /opt/ph/verify.log 2>&1 &); done
sleep 20; while pgrep -f verify_dataset.py >/dev/null; do sleep 20; done; cp /opt/ph/verify.log /opt/ph/verify_final.log; up verify_final.log
echo STAGE-E-DONE > /opt/ph/stage_e.done; up stage_e.done
