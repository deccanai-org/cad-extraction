#!/usr/bin/env bash
set -Eeuo pipefail

region=ap-south-1
aws_bin=/usr/local/bin/aws
run_id=sds2-step-r2-20260929-01
instance_id=i-0a9be41d2cdd4ad80
output=s3://annotationprod/cad-disk-extract/${run_id}/shards/shard-00
candidate=/opt/sds2-v6-parallel-shard00
manifest=/opt/sds2-v4/shard-00.json
zip_sha=ede2da980e2bf150715cf3c879c7842800a4399fe7d8610f93003f7ab9343c1e
manifest_sha=c65cbbc8069113d8abb488c2b597954c5d418df1f9c2f50626b3d74f869e23b4

token=$(curl -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 3600' http://169.254.169.254/latest/api/token)
actual_id=$(curl -fsS -H "X-aws-ec2-metadata-token: ${token}" http://169.254.169.254/latest/meta-data/instance-id)
[[ "$actual_id" == "$instance_id" ]] || { echo "unexpected instance: $actual_id" >&2; exit 22; }
mountpoint -q /data || { echo '/data not mounted' >&2; exit 21; }
printf '%s  %s\n' "$zip_sha" "$candidate/pipeline.zip" | sha256sum -c -
printf '%s  %s\n' "$manifest_sha" "$manifest" | sha256sum -c -
test -s /data/out-r2/results.jsonl
mkdir -p /data/work-v6-shard00 /data/logs

cd "$candidate/sds2-step-pipeline"
/root/sds2env/bin/python -m py_compile batch/run_batch.py decode/sds2_to_step.py decode/to_step2.py decode/verify_step.py
"$aws_bin" s3 cp /data/out-r2/results.jsonl "$output/results.jsonl" --region "$region" --only-show-errors
printf '{"schema":"sds2-step-worker/v2","run_id":"%s","instance_id":"%s","shard":"00","state":"parallel_rebalance_running","pipeline_sha256":"%s","started_at":"%s"}\n' \
  "$run_id" "$instance_id" "$zip_sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$candidate/worker-v6.json"
"$aws_bin" s3 cp "$candidate/worker-v6.json" "$output/worker-v6.json" --region "$region" --only-show-errors

set +e
/root/sds2env/bin/python -u batch/run_batch.py \
  --s3 --items "$manifest" \
  --out /data/out-r2 --work /data/work-v6-shard00 \
  --upload "$output" --delete-local --no-fallback \
  --jobs-per-archive 16 --convert-jobs 16 --workers 20 --downloads 4 \
  --min-free-gb 24 --min-disk-gb 100 --timeout 14400 \
  > /data/logs/v6-shard00-parallel.log 2>&1
run_rc=$?
set -e
"$aws_bin" s3 cp /data/logs/v6-shard00-parallel.log "$output/run-v6.log" --region "$region" --only-show-errors || true
state=runner_completed
if (( run_rc != 0 )); then state=runner_failed; fi
printf '{"schema":"sds2-step-worker/v2","run_id":"%s","instance_id":"%s","shard":"00","state":"%s","exit_code":%s,"pipeline_sha256":"%s","finished_at":"%s"}\n' \
  "$run_id" "$instance_id" "$state" "$run_rc" "$zip_sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$candidate/worker-v6.json"
"$aws_bin" s3 cp "$candidate/worker-v6.json" "$output/worker-v6.json" --region "$region" --only-show-errors
"$aws_bin" s3 cp "$candidate/worker-v6.json" "$output/worker.json" --region "$region" --only-show-errors
echo "parallel shard00 finished: $state rc=$run_rc"
exit "$run_rc"
