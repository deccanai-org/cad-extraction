#!/bin/bash
# BOX-A: offline test of the patched grade/worker.py check_step (stub S3 = local m2.step); <= 3 threads
cd /work/agentwork/step-verify-big && rm -rf itest && mkdir -p itest && cd itest
aws s3 cp --only-show-errors --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/step-verify-big/itest/ .
mkdir -p s3local && ln -sf /work/agentwork/step-verify-big/in/m2.step s3local/m2.step
setsid nohup bash -c "SVB_WORKERS=2 SVB_MEM_GB=6 /opt/conv/env/bin/python test_check_step.py kit s3local/m2.step > itest.log 2>&1; aws s3 cp --only-show-errors itest.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/itest/itest.log" > /dev/null 2>&1 < /dev/null &
echo started
