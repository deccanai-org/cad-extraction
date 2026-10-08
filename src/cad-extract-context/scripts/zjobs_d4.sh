#!/bin/bash
# Job builder for zentitude-data-4 (phase 2), after the census (same box, same work dir /opt/zcensus/d4).
# Reads the census parts, the data-3 index + its job lists (reuse by sha), data-4 dedup markers, the Disk-1/2 sha map (annotationprod
# agentwork/pkg-resolver, read-only) and the Disk-1/2 db1_jobs list. Writes ONLY bim cad-disk-extract/zentitude-data-4/_state/conv2/:
#   scan/contents_{ifc,db1,sds2}.jsonl.gz, scan/jobs_summary.json, {ifc,db1,sds2}/jobs.json, sds2/files/<fpc>.json.gz
# No deletes; nothing is converted by this script (the disk-lane workers start only once a pipeline env lists disk_lanes).
# Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/zjobs_d4.sh 300
#  - kit: z3conv/scan/{zcensus,zjobs}.py from the control prefix (deploy.sh scan); one-off transient unit zjobs-d4 at nice 19
#  - idempotent: later calls print progress, then the summary
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; O=/opt/zcensus; K=$O/kit
mkdir -p $O $K
if [ -f $O/finished.jobs.d4 ]; then echo "finished $(cat $O/finished.jobs.d4)"; tail -n 3 $O/log.jobs.d4.txt | cut -c1-8000; exit 0; fi
if systemctl is-active -q zjobs-d4; then echo "running since $(cat $O/started.jobs.d4)"; tail -n 4 $O/log.jobs.d4.txt; exit 0; fi
[ -f $O/finished.d4 ] && grep -q CENSUS $O/log.d4.txt || { echo "census not finished: run zcensus_d4.sh first"; exit 1; }
for f in zcensus.py zjobs.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/scan/$f $K/$f || exit 1; done
sha256sum $K/zcensus.py $K/zjobs.py
date -u +%FT%TZ > $O/started.jobs.d4
systemctl reset-failed zjobs-d4 2>/dev/null
systemd-run --unit=zjobs-d4 --collect --nice=19 --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=CENSUS_WORK=$O/d4 --working-directory=$K /bin/bash -c \
  "$PY $K/zjobs.py zentitude-data-4 > $O/log.jobs.d4.txt 2>&1; echo rc=\$? >> $O/log.jobs.d4.txt; date -u +%FT%TZ > $O/finished.jobs.d4"
sleep 60
tail -n 4 $O/log.jobs.d4.txt
