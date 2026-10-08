#!/bin/bash
W=/work/agentwork/audit-sds2-pipeline
cd $W
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/sds2-step-pipeline-v5.4.zip . --quiet --region ap-south-1
echo "bf4a07fc3878ba29311b5c3d78c00519366ac361fd39cfbb2ee930b0dfb2f906  sds2-step-pipeline-v5.4.zip" | sha256sum -c - >> go54.log 2>&1 || exit 1
rm -rf v54 && mkdir v54 && (cd v54 && /opt/conv/env/bin/python -c "import zipfile;zipfile.ZipFile('../sds2-step-pipeline-v5.4.zip').extractall('.')")
/opt/conv/env/bin/python d5b.py > d5b.log 2>&1
aws s3 cp d5b.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/diag54/d5b.log --quiet --region ap-south-1
