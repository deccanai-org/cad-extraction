#!/bin/bash
# Standalone runner (no convfleet): run every open job of the package job list once, N in parallel. Fleet box only.
#   aws s3 cp s3://annotationprod/cad-disk-extract/_control/packaging_d3/code/ /opt/pkg/ --recursive && bash /opt/pkg/kit/run_package_standalone.sh 8
set -euo pipefail
export AWS_DEFAULT_REGION=ap-south-1 PKG_ALLOW_WRITE=1
N=${1:-8}; D=/opt/pkg; W=${PKG_WORK:-/scratch/pkgwork}; mkdir -p "$W" "$D/jobs"
PY=${PKG_PY:-python3}
JK=${PKG_JOBS_KEY:-cad-disk-extract/zenitude-data-3/_state/conv/package/jobs.json}
aws s3 cp "s3://bim-proprietary-data/$JK" - | $PY -c '
import json,sys,os
d=json.load(sys.stdin)
for j in d["jobs"]:
    json.dump(j, open(os.path.join("'"$D"'/jobs", j["id"]+".json"),"w"))
print(len(d["jobs"]))'
ls "$D"/jobs/*.json | xargs -P "$N" -I{} sh -c 'cd '"$D"' && '"$PY"' pkg.py job --job {} --workdir '"$W"'/$(basename {} .json) >> '"$W"'/$(basename {} .json).log 2>&1; echo "$(date -u +%FT%TZ) $(basename {}) rc=$?"'
