#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W
timeout 40 /opt/conv/env/bin/python explain.py 5f50b5bd v4c 2>&1 | grep -E "^Shoal|SHOAL|role angle|missing_holes|nc1x|status x" | head -14
timeout 40 /opt/conv/env/bin/python explain.py 8ff03e42 2>&1 | grep -E "SEASIDE|role|missing_holes|count_equal|extra|nc1x|status x" | head -16
ls cache/ifc_*.npz | wc -l
