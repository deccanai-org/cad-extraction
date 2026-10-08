#!/bin/bash
# run once the owner's SSO login is back (lead 08:05Z: no control writes / SSM before)
set -e
export AWS_PROFILE=annotationprod-publish
aws s3 ls s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/converter.json > /dev/null
cd /Users/dhiren/Downloads/Deccan/z3conv && bash deploy.sh ifc db1 sds2 grade final coord
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
aws s3 cp --quiet /tmp/z3c/db1_env.login.json $CTL/db1/env.json
aws s3 cp --quiet /tmp/z3c/grade_env.login.json $CTL/grade/env.json
echo "deployed $(date -u +%H:%MZ)"
