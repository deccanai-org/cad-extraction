set -e
W=/work/agentwork/ifc-surface-to-solid; mkdir -p $W/census && cd $W/census
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-surface-to-solid/census.py .
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-surface-to-solid/ids.json .
timeout 600 /opt/conv/env/bin/python census.py > census.log 2>&1 || true
aws s3 cp --quiet census_summary.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-surface-to-solid/census_summary.json
aws s3 cp --quiet census_out.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-surface-to-solid/census_out.json
tail -c 3000 census.log
