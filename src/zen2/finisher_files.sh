#!/bin/bash
# finisher_files.sh (runs on cad-zen2-files) - wait until every Z4 conversion pipeline is final, write one last conv_status pass,
# back up /work state to S3, then shut down (instance-initiated shutdown behaviour = terminate). Safety net if the lead's SSO expires.
LOG=/work/finisher.log
S=s3://annotationprod/cad-disk-extract/zentitude-data-4/_state
DEADLINE=$(date -u -d '2026-09-30T18:00:00Z' +%s)
prev=""; stable=0
while true; do
  st=$(aws s3 cp --quiet $S/conv_status.json - 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)['pipelines']
fin=all(d[k]['done']>=d[k]['jobs'] and not d[k].get('in_flight') and not d[k].get('pending') for k in ('ifc','db1','sds2'))
print(('FINAL' if fin else 'RUN'), ' '.join(f\"{k}:{d[k]['done']}/{d[k]['ok']}/{d[k]['failed']}\" for k in ('ifc','db1','sds2')))" 2>/dev/null)
  flag=$(aws s3 cp --quiet $S/conv_final.json - 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('final'))" 2>/dev/null)
  if [[ "$st" == FINAL* ]] && [ "$st" == "$prev" ]; then stable=$((stable+1)); elif [[ "$st" == FINAL* ]]; then stable=1; else stable=0; fi
  prev="$st"
  echo "$(date -u +%FT%TZ) $st | builder_final=$flag | stable=$stable" >> $LOG
  [ "$flag" == "True" ] && [[ "$st" == FINAL* ]] && break
  [ $stable -ge 4 ] && break                                   # final and unchanged for 30+ min (no requeues pending)
  [ $(date -u +%s) -ge $DEADLINE ] && { echo "deadline reached" >> $LOG; break; }
  sleep 600
done
echo "$(date -u +%FT%TZ) finishing: final conv_status pass" >> $LOG
(cd /work/conv4/status && timeout 900 python3 conv_status.py >> $LOG 2>&1)
pkill -f "conv_status.py --loop"; pkill -f /work/pdf_classify.py; sleep 5
D4=s3://annotationprod/cad-disk-extract/zentitude-data-4/_state/box_backup/cad-zen2-files/work
D2=s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/box_backup/cad-zen2-files/work
rc_all=0
cd /work
for item in *; do
  case "$item" in out|in|zxr|lost+found) continue;; esac
  case "$item" in 2d|md) DST=$D2;; *) DST=$D4;; esac
  if [ -d "$item" ]; then /usr/local/bin/s5cmd --numworkers 64 sync "/work/$item/" "$DST/$item/" >> /work/finisher_s5.log 2>&1
  else /usr/local/bin/s5cmd cp "/work/$item" "$DST/$item" >> /work/finisher_s5.log 2>&1; fi
  rc=$?; [ $rc -ne 0 ] && { rc_all=$rc; echo "backup FAILED for $item rc=$rc" >> $LOG; }
done
/usr/local/bin/s5cmd cp /work/finisher.log "$D4/finisher.log" > /dev/null 2>&1
if [ $rc_all -ne 0 ]; then echo "$(date -u +%FT%TZ) backup had errors - NOT shutting down" >> $LOG; /usr/local/bin/s5cmd cp /work/finisher.log "$D4/finisher.log"; exit 1; fi
echo "{\"done\": \"$(date -u +%FT%TZ)\", \"status\": \"$prev\"}" | aws s3 cp - "$D4/DONE.json"
echo "$(date -u +%FT%TZ) backup complete; shutting down (terminate)" >> $LOG
/usr/local/bin/s5cmd cp /work/finisher.log "$D4/finisher.log" > /dev/null 2>&1
shutdown -h now
