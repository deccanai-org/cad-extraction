#!/bin/bash
# wait for all 256 chunks .done (any host), then: local results -> S3, retry failures, model index, final status
cd /work/2d; L=/work/md/state/md_finish.log
B=s3://annotationprod/cad-disk-extract/zenitude-data-2
while pgrep -f "md_run.py 28" > /dev/null; do sleep 60; done
while [ "$(aws s3 ls $B/_state/d2_md_claims/ | grep -c '\.done$')" -lt 256 ]; do echo "$(date -u +%T) waiting for other hosts: $(aws s3 ls $B/_state/d2_md_claims/ | grep -c '\.done$') done" >> $L; sleep 120; done
cat /work/md/state/results_sha.jsonl /work/md/state/results_pcf.jsonl | gzip > /tmp/aa-local.jsonl.gz
aws s3 cp --only-show-errors /tmp/aa-local.jsonl.gz $B/_state/d2_md_results/aa-local-$(hostname).jsonl.gz
echo "$(date -u +%T) retry failed" >> $L
./venv/bin/python md_run.py 28 --retry-failed >> $L 2>&1
echo "$(date -u +%T) model index" >> $L
./venv/bin/python md_index.py >> $L 2>&1
./venv/bin/python md_status_final.py >> $L 2>&1
echo "$(date -u +%T) MD FINISH DONE" >> $L
