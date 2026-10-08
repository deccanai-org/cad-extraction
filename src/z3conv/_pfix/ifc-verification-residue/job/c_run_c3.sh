#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue/sds2; cd $W
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/sds2/calsurvey.py .
SPY=/work/agentwork/sds2v54/env/bin/python
J=""; for id in c88c625fc594c3baf4cf75e4 82c72b44deea79e67c269eb6 9b72c7bcefc4fe11f5e228fa 40e0ff87a224295965571bd3 01f4088b1de357eafa7dcfdb a313a9543e7cc59629c7277f 490530dbbebc724f5339ad33 b42d0b1d3af9debc9a75fee3; do J="$J $(dirname $(find jobs/$id -name mem_idx | head -1))/.."; done
$SPY calsurvey.py $W/v5.4/sds2-step-pipeline/decode $J 2>&1 | grep '^{'
