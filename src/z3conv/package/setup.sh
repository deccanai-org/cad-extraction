#!/bin/bash
# 'package' vpipe kit setup: nothing to build. The worker runs on the fleet's env python, which needs boto3 >= 1.34
# (CopyObject ChecksumAlgorithm / HeadObject ChecksumMode). Called as: bash setup.sh <CONV_HOME> <kit dir>
W=${1:-/opt/conv}
"$W/env/bin/python" -c "import boto3; v = tuple(int(x) for x in boto3.__version__.split('.')[:2]); assert v >= (1, 34), boto3.__version__; print('package kit: boto3', boto3.__version__)"
