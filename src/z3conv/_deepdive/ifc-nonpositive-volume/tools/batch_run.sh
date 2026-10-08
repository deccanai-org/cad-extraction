#!/bin/bash
cd /Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-nonpositive-volume
xargs -P 3 -n 1 tools/batch_one.sh < batch_small.txt
xargs -P 2 -n 1 tools/batch_one.sh < batch_large.txt
echo BATCH_DONE
