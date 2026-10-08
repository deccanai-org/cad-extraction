W=/work/agentwork/sds2v54; cd $W; mkdir -p nc1
export AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54/nc1reach.py $W/nc1reach.py
[ -f $W/d3jobs.json ] || aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/sds2/jobs.json $W/d3jobs.json
timeout 5400 $W/env/bin/python $W/nc1reach.py > $W/nc1/nc1reach.out 2>&1
aws s3 cp --quiet $W/nc1/nc1reach.jsonl s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/nc1/nc1reach.jsonl
aws s3 cp --quiet $W/nc1/nc1reach.out s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/nc1/nc1reach.out
