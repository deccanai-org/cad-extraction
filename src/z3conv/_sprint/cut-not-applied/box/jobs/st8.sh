#!/bin/bash
cd /work/agentwork/cut-not-applied; tail -2 res/bboxpair_gambro.txt 2>/dev/null; ps -eo pid,etime,cmd | grep "[b]box_pair" | head -3 | cut -c1-140
