#!/bin/bash
exec >> /opt/pkg/endgame.log 2>&1
set -x
C=s3://annotationprod/cad-disk-extract/_control/packaging
cd /opt/pkg
aws s3 cp --region ap-south-1 --quiet $C/endgame/endgame.py /opt/pkg/endgame.py
EG="python3 /opt/pkg/endgame.py"
( while true; do aws s3 cp --region ap-south-1 --quiet /opt/pkg/endgame.log $C/endgame/log_$(hostname).txt; sleep 60; done ) &
until grep -q ALLDONE /opt/pkg/retry.log 2>/dev/null; do sleep 60; done; until $EG mark ifc1_done_hyd; do sleep 10; done
until $EG wait marker:db1_plan_ready; do sleep 30; done
aws s3 cp --region ap-south-1 --quiet $C/pkg_step_latest.py /opt/pkg/pkg_step.py
aws s3 cp --region ap-south-1 --quiet $C/step_v1_db1/db1_pack_check.py /opt/pkg/db1_pack_check.py
for pass in 1 2 3 4 5; do
  for i in $(seq 14 29); do for j in 0 1 2; do (PKG_SOURCES=db1 PKG_SHARD=$i/30 PKG_SUBSHARD=$j/3 THREADS=48 PROJ_THREADS=1 python3 /opt/pkg/pkg_step.py apply >> /opt/pkg/db1_shard_${i}_$j.log 2>&1 &); done; done
  sleep 20; while pgrep -f "pkg_step.py apply" >/dev/null; do sleep 30; done
  python3 /opt/pkg/db1_pack_check.py 14 29 30 && break
done
until $EG mark db1pack_done_hyd; do sleep 10; done
until $EG wait marker:ifc2_done; do sleep 30; done
for pass in 1 2; do
  for i in $(seq 14 29); do (PKG_SOURCES=retag PKG_SHARD=$i/30 THREADS=16 python3 /opt/pkg/pkg_step.py retag >> /opt/pkg/retag_$i.log 2>&1 &); done
  sleep 20; while pgrep -f "pkg_step.py retag" >/dev/null; do sleep 30; done
  grep -q ERROR /opt/pkg/retag_*.log || break
done
until $EG mark retag_done_hyd; do sleep 10; done
until $EG wait marker:retag_done_mum; do sleep 30; done
aws s3 cp --region ap-south-1 --quiet $C/verify/verify_dataset.py /opt/pkg/verify_dataset.py
for i in 8 9 10 11 12 13 14 15; do (VERIFY_SHARD=$i/16 python3 /opt/pkg/verify_dataset.py >> /opt/pkg/verify.log 2>&1 &); done
sleep 20; while pgrep -f verify_dataset.py >/dev/null; do sleep 30; done
until $EG mark verify_done_hyd; do sleep 10; done
aws s3 cp --region ap-south-1 --quiet /opt/pkg/endgame.log $C/endgame/log_$(hostname).final.txt
for f in /opt/pkg/*.log; do aws s3 cp --region ap-south-1 --quiet $f $C/endgame/logs_$(hostname)/$(basename $f); done
shutdown -h +2
