#!/bin/bash
# audit-sds2-v5x box job.  usage: bash job.sh sync|audit|all   (runs in /work/agentwork/audit-sds2-v5x)
# sync: read-only copies of the SDS2 fleet state + published outputs (no STEP/PNG/pieces.csv), converter zips unpacked per label
# audit: python audit5x.py -> out/ ; results uploaded to s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-v5x/
set -u
export AWS_DEFAULT_REGION=ap-south-1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
D=/work/agentwork/audit-sds2-v5x; cd $D
B=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3
ST=$B/_state/conv/sds2
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
R=$B/_state/agentwork/audit-sds2-v5x
MODE=${1:-all}
note() { echo "$(date -u +%FT%TZ) $*" | tee -a $D/progress.txt; aws s3 cp --quiet $D/progress.txt $R/progress.txt; }

if [ "$MODE" = sync ] || [ "$MODE" = all ]; then
  note "sync start"
  mkdir -p s3/sds2 s3/out s3/conv/history s3/ctl code
  # 2 syncs at a time (~20 request threads)
  ( aws s3 sync --only-show-errors $ST/results/ s3/sds2/results/ ; aws s3 sync --only-show-errors $ST/deferred/ s3/sds2/deferred/ ;
    aws s3 sync --only-show-errors $ST/claims/ s3/sds2/claims/ ; aws s3 sync --only-show-errors $ST/hosts/ s3/sds2/hosts/ ;
    aws s3 sync --only-show-errors $ST/retry/ s3/sds2/retry/ ;
    for f in jobs.json redo.json jobs_reconvert.json; do aws s3 cp --quiet $ST/$f s3/sds2/$f; done ;
    aws s3 sync --only-show-errors $ST/logs/ s3/sds2/logs/ ; aws s3 sync --only-show-errors $ST/boxlogs/ s3/sds2/boxlogs/ ) &
  ( aws s3 sync --only-show-errors $B/conversions/sds2-step/ s3/out/ --exclude '*.step' --exclude '*.png' --exclude '*_pieces.csv' ;
    aws s3 ls --recursive $B/conversions/sds2-step/ > s3/out_listing.txt ) &
  wait
  note "sync state+outputs done"
  for f in index.jsonl.gz history.json class2_fix_plan.json index_summary.json; do aws s3 cp --quiet $B/_state/conv/$f s3/conv/$f; done
  aws s3 sync --only-show-errors $B/_state/conv/history/ s3/conv/history/
  aws s3 cp --quiet $B/_state/conv/scan/sds2_versions.json s3/conv/sds2_versions.json
  aws s3 cp --quiet $B/_state/conv/scan/contents_sds2.jsonl.gz s3/conv/contents_sds2.jsonl.gz
  aws s3 cp --quiet $B/_state/conv_status.json s3/conv_status.json
  for f in build_index.py grade_join.py reconvert.json rules.json; do aws s3 cp --quiet $CTL/coord/$f s3/ctl/$f; done
  for f in converter.json canary.json env.json worker.py convfleet.py; do aws s3 cp --quiet $CTL/sds2/$f s3/ctl/sds2_$f; done
  for z in v4-candidate v5 v5.1 v5.2 v5.3; do
    if [ ! -d code/$z ]; then aws s3 cp --quiet $CTL/sds2/sds2-step-pipeline-$z.zip code/$z.zip && mkdir -p code/$z && (cd code/$z && unzip -q ../$z.zip) ; fi
  done
  note "sync done: results=$(ls s3/sds2/results | wc -l) logs=$(ls s3/sds2/logs | wc -l) outdirs=$(ls s3/out | wc -l) steps=$(grep -c '\.step$' s3/out_listing.txt)"
fi

if [ "$MODE" = audit ] || [ "$MODE" = all ]; then
  note "audit start"
  INDEX_WORK=$D/idxwork /opt/conv/env/bin/python $D/audit5x.py > $D/audit.log 2>&1; rc=$?
  note "audit rc=$rc"
  aws s3 cp --quiet $D/audit.log $R/audit.log
  aws s3 sync --only-show-errors $D/out/ $R/out/
  note "uploaded"
fi
