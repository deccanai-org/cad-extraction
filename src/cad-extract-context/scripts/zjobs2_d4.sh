#!/bin/bash
# Second input-resolution pass for zentitude-data-4 (after zjobs_d4.sh): the 4,082 IFC + 2,465 DB1 contents data-4 stored only as
# Disk-1/2 pointers. Candidates: DB1 earlier-run source keys (Disk-1/2 db1-v2 / Windows results), and the Disk-1 / Disk-2 extraction of
# the byte-identical archive at the same member path + size. Every candidate is PROVEN before use (S3 ChecksumSHA256, else sha256 of the
# streamed bytes = the content sha256). READ-ONLY on Disk-1/2 and sources; writes ONLY bim cad-disk-extract/zentitude-data-4/_state/conv2/
# ({ifc,db1}/jobs.json: proven contents appended, the list only grows; scan/contents_{ifc,db1}.jsonl.gz; scan/jobs_summary.json pass2).
# No deletes. Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/zjobs2_d4.sh 300
#  - kit: z3conv/scan/{zcensus,zjobs2}.py from the control prefix (deploy.sh scan); one-off transient unit zjobs2-d4 at nice 19
#  - idempotent: later calls print progress, then the summary
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; O=/opt/zcensus; K=$O/kit
mkdir -p $O $K
if [ -f $O/finished.jobs2.d4 ]; then echo "finished $(cat $O/finished.jobs2.d4)"; tail -n 3 $O/log.jobs2.d4.txt | cut -c1-8000; exit 0; fi
if systemctl is-active -q zjobs2-d4; then echo "running since $(cat $O/started.jobs2.d4)"; tail -n 4 $O/log.jobs2.d4.txt; exit 0; fi
[ -f $O/finished.jobs.d4 ] && grep -q JOBS $O/log.jobs.d4.txt || { echo "job builder not finished: run zjobs_d4.sh first"; exit 1; }
for f in zcensus.py zjobs2.py; do aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/scan/$f $K/$f || exit 1; done
sha256sum $K/zcensus.py $K/zjobs2.py
date -u +%FT%TZ > $O/started.jobs2.d4
systemctl reset-failed zjobs2-d4 2>/dev/null
systemd-run --unit=zjobs2-d4 --collect --nice=19 --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=CENSUS_WORK=$O/d4 --working-directory=$K /bin/bash -c \
  "$PY $K/zjobs2.py zentitude-data-4 > $O/log.jobs2.d4.txt 2>&1; echo rc=\$? >> $O/log.jobs2.d4.txt; date -u +%FT%TZ > $O/finished.jobs2.d4"
sleep 60
tail -n 4 $O/log.jobs2.d4.txt
