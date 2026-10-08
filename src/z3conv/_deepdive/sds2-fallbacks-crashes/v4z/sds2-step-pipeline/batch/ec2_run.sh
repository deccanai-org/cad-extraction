#!/usr/bin/env bash
# Launch the Disk-2 batch inside tmux so it survives SSH disconnects; re-running this resumes (results.jsonl is kept
# locally and in S3, so a replacement / spot instance continues where the last one stopped).
#
# usage: bash batch/ec2_run.sh s3://YOUR-BUCKET/sds2-step [extra run_batch.py args...]
#   e.g. bash batch/ec2_run.sh s3://my-bucket/sds2-step --limit 20            # smoke test first
#        bash batch/ec2_run.sh s3://my-bucket/sds2-step                       # everything
#        bash batch/ec2_run.sh s3://my-bucket/sds2-step --versions 7.3 2019   # a subset
# env:  DATA=/data (work + local output root), JOBS=<conversions at once; default from cores / RAM>
set -euo pipefail
cd "$(dirname "$0")/.."
UPLOAD="${1:?give the output location, e.g. s3://my-bucket/sds2-step}"; shift
DATA="${DATA:-/data}"
mkdir -p "$DATA/out" "$DATA/work" "$DATA/logs"
JOBARG=(); [ -n "${JOBS:-}" ] && JOBARG=(--convert-jobs "$JOBS")
LOG="$DATA/logs/batch_$(date +%Y%m%d_%H%M%S).log"
CMD="source $HOME/sds2env/bin/activate && python -u batch/run_batch.py --s3 --out $DATA/out --work $DATA/work \
 --upload $UPLOAD --delete-local ${JOBARG[*]:-} $* 2>&1 | tee $LOG"
tmux new-session -d -s sds2 "$CMD; echo finished; sleep 86400" \
  || { echo "tmux session 'sds2' already running: tmux attach -t sds2"; exit 1; }
echo "started in tmux session 'sds2' (tmux attach -t sds2), log: $LOG"
echo "progress: grep -c '\"status\"' $DATA/out/results.jsonl ; summary at the end: $DATA/out/summary.md"
