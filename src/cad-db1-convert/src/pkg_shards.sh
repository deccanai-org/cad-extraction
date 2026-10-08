# run packaging shards FIRST..LAST of N on this box (idempotent; one project never in two shards)
set +e
SRC=${PKG_SOURCES:-ifc}; FIRST=${FIRST:-0}; LAST=${LAST:-13}; N=${N:-30}
S=s3://annotationprod/cad-disk-extract/_control/packaging/step_v1_$SRC
pkill -f /var/lib/cloud/instance/scripts/part-001 ; sleep 1; pkill -f pkg_step.py; sleep 3
mkdir -p /opt/pkg && cd /opt/pkg
aws s3 cp --region ap-south-1 --quiet $S/pkg_step.py /opt/pkg/pkg_step.py
for i in $(seq $FIRST $LAST); do
  (PKG_SOURCES=$SRC PKG_SHARD=$i/$N THREADS=48 PROJ_THREADS=1 nohup python3 /opt/pkg/pkg_step.py apply > /opt/pkg/shard_$i.log 2>&1 &)
done
# log sync: every minute push a combined tail + done/error counts
(nohup bash -c "while true; do for f in /opt/pkg/shard_*.log; do echo \"== \$f\"; tail -3 \$f; done > /opt/pkg/status.txt; aws s3 cp --region ap-south-1 --quiet /opt/pkg/status.txt $S/status_\$(hostname).txt; sleep 60; done" > /dev/null 2>&1 &)
sleep 20; pgrep -fc "pkg_step.py apply"; tail -1 /opt/pkg/shard_$FIRST.log
