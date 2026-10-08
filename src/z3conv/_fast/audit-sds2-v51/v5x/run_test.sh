#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
D=/work/agentwork/audit-sds2-v5x; cd $D && rm -rf $D/fixes/base
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/audit-sds2-v5x/fixes/ $D/fixes/
sha256sum $D/fixes/base/convfleet.py $D/fixes/convfleet.py
cd $D/fixes && timeout 100 /opt/conv/env/bin/python test_patches.py > test.log 2>&1; echo "test rc=$?"; grep -E "EXPECT" test.log
aws s3 cp --quiet test.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-v5x/fixes/test_final.log
aws s3 cp --quiet test_patches_result.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-v5x/fixes/test_patches_result_final.json
