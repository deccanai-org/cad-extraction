cd /opt/ph
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc
F=$C/fix; RR=s3://annotationprod/cad-disk-extract
A="aws s3 cp --region ap-south-1 --quiet"
up() { for f in "$@"; do $A /opt/ph/$f $C/$f; done; }
until [ -f /opt/ph/probe/regen.log ] && grep -q "regen rc" /opt/ph/probe/regen.log; do sleep 15; done
: > /opt/ph/publish.log
for s in b5e0694a4b02a8ecced6c4128b00d8a941e23756574f6a8959a45bc178df7d1e 9c2e39cb0fcfc14665403bc76e27aba7c3a17e7578f1c5c448824856d8dadda2; do
  j=/opt/ph/probe/${s:0:12}/regen_summary.json
  if python3 -c "import json,sys; d=json.load(open('$j')); sys.exit(0 if d['ok'] and d['absurd_points']==0 and d['parts']==d['parts_before'] and d['written']==d['written_before'] else 1)"; then
    $A $RR/_state/db1-v2/results/$s.json $RR/_state/db1-v2/results_superseded/$s.json
    $A /opt/ph/probe/${s:0:12}/fixed.stp $RR/conversions/db1-step/$s.stp --content-type application/step
    $A /opt/ph/probe/${s:0:12}/new_result.json $RR/_state/db1-v2/results/$s.json --content-type application/json
    echo "published $s" >> /opt/ph/publish.log
  else echo "NOT published $s $(cat $j)" >> /opt/ph/publish.log; fi
done
up publish.log
$A $C/refresh_packaged.py /opt/ph/refresh_packaged.py
sed -i 's/^os.environ.setdefault("AWS_PROFILE", "bim")$/os.environ.pop("AWS_PROFILE", None)/' /opt/ph/refresh_packaged.py
PKG_SOURCES=db1 PKG_STATE=cad-disk-extract/_control/packaging/step_v1_db1_posthoc2 THREADS=64 python3 /opt/ph/pkg_posthoc_run.py plan > /opt/ph/plan2.log 2>&1; echo "plan2 rc=$?" >> /opt/ph/plan2.log; up plan2.log
PKG_SOURCES=db1 PKG_STATE=cad-disk-extract/_control/packaging/step_v1_db1_posthoc2 THREADS=64 PROJ_THREADS=16 python3 /opt/ph/pkg_posthoc_run.py apply > /opt/ph/apply2.log 2>&1; echo "apply2 rc=$?" >> /opt/ph/apply2.log; up apply2.log
THREADS=64 python3 /opt/ph/refresh_packaged.py --apply > /opt/ph/refresh2.log 2>&1; echo "refresh2 rc=$?" >> /opt/ph/refresh2.log; up refresh2.log
rm -f /opt/ph/verify.log
for i in $(seq 0 15); do (VERIFY_SHARD=$i/16 python3 /opt/ph/verify_dataset.py >> /opt/ph/verify.log 2>&1 &); done
sleep 20; while pgrep -f verify_dataset.py >/dev/null; do sleep 20; done; up verify.log
echo STAGE-D-DONE > /opt/ph/stage_d.done; up stage_d.done
