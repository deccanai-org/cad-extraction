#!/bin/bash
# run_all.sh VER [PAR] : all fetched jobs (largest first) through run_one.sh
V=$1; PAR=${2:-14}
cd /data/jobs
for d in $(cat /data/jobs/dirs.txt); do echo "$(du -s "$d" | cut -f1) $d"; done | sort -rn | cut -d' ' -f2- > /data/jobs/order.txt
cat /data/jobs/order.txt | xargs -P $PAR -I{} bash /opt/v5dev/run_one.sh $V {}
echo "$(date -u +%FT%TZ) $V done" >> /data/out/runs.done
