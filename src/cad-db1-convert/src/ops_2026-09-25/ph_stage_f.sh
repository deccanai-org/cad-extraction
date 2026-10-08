cd /opt/ph
C=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_db1_posthoc
A="aws s3 cp --region ap-south-1 --quiet"
up() { for f in "$@"; do $A /opt/ph/$f $C/$f; done; }
until [ -f /opt/ph/stage_e.done ]; do sleep 30; done
# wait until the worker's own rule says both Teton re-runs are final
until python3 -c "
import sys; sys.path.insert(0, '/opt/db1v2'); import db1_worker as w
sys.exit(0 if all(w.done_now(s) for s in ['a3200ff3949dfe7883c45d9aee386a522b00997b43e441dcfb0be6a1d464838f','f8f6249901b56fb32663e3c1d6eb7f4aa4a0146271166ade14c280d9e9cb826c']) else 1)" >/dev/null 2>&1; do sleep 60; done
THREADS=64 python3 /opt/ph/refresh_packaged.py --apply > /opt/ph/refresh3.log 2>&1; echo "refresh3 rc=$?" >> /opt/ph/refresh3.log; up refresh3.log
rm -f /opt/ph/verify.log
for i in $(seq 0 15); do (VERIFY_SHARD=$i/16 python3 /opt/ph/verify_dataset.py >> /opt/ph/verify.log 2>&1 &); done
sleep 20; while pgrep -f verify_dataset.py >/dev/null; do sleep 20; done; cp /opt/ph/verify.log /opt/ph/verify_final2.log; up verify_final2.log
echo STAGE-F-DONE > /opt/ph/stage_f.done; up stage_f.done
