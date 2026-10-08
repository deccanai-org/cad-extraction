#!/bin/bash
# F.sh RELPATH : print an agentwork result file from S3
AWS_PROFILE=bim aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied/$1 -
