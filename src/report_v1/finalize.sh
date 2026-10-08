#!/bin/bash
# pull the finisher's final results and build the report (publish with the Artifact tool afterwards)
cd "$(dirname "$0")"
export AWS_PROFILE=${AWS_PROFILE:-annotationprod-publish}
for f in FINISH_DONE.json stats_f1.json projects_f1.json stats_p1.json projects_p1.json class_final.json verify_perfect.json verify_partial.json; do
  aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/_state/report/out/$f data/$f || echo "missing $f"
done
python3 build_report.py f1 p1 class_final.json
