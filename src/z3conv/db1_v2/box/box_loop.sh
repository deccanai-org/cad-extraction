#!/bin/bash
# task loop: every 30 s sync $CTL/tasks/*.sh; run each new task (once) in the background with its log streamed to S3.
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box
OUT=s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2
W=/opt/v2; cd $W
last=$(date +%s)
hb() { echo "{\"t\":\"$(date -u +%FT%TZ)\",\"running\":$(ls $W/run 2>/dev/null | wc -l),\"load\":\"$(cut -d' ' -f1-3 /proc/loadavg)\",\"mem_free_mb\":$(free -m | awk '/Mem/{print $7}'),\"disk_free_gb\":$(df -BG --output=avail / | tail -1 | tr -dc 0-9)}" > $W/hb.json; aws s3 cp --quiet $W/hb.json $OUT/box/hb.json; }
mkdir -p $W/run
while true; do
  if aws s3 ls $CTL/stop > /dev/null 2>&1; then echo "stop flag"; hb; break; fi
  aws s3 sync --quiet $CTL/tasks/ $W/tasks/ 2>/dev/null
  for t in $W/tasks/*.sh; do
    [ -f "$t" ] || continue; n=$(basename $t .sh)
    [ -f $W/done/$n ] && continue; [ -f $W/run/$n ] && continue
    touch $W/run/$n; last=$(date +%s)
    ( cd $W; bash $t > $W/out/$n.log 2>&1; echo "rc=$?" >> $W/out/$n.log; aws s3 cp --quiet $W/out/$n.log $OUT/box/logs/$n.log; rm -f $W/run/$n; touch $W/done/$n ) &
  done
  for f in $W/run/*; do [ -f "$f" ] && aws s3 cp --quiet $W/out/$(basename $f).log $OUT/box/logs/$(basename $f).log; done
  [ "$(ls $W/run | wc -l)" -gt 0 ] && last=$(date +%s)
  avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
  if [ "$avail" -lt 1200 ]; then echo "$(date -u) low memory $avail MB: killing newest python"; pkill -n -f python3; fi
  hb
  if [ $(( $(date +%s) - last )) -gt 7200 ]; then echo "idle 2h"; break; fi
  sleep 30
done
