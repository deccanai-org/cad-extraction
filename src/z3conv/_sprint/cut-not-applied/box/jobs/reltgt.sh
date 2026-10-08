#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
P=/opt/conv/ifc84/bin/python
$P tools/old_rel_targets.py kitp2 src/0762effe61de88c0.db1 12,9,34 id2 2>&1 | cut -c1-400 | head -60
$P tools/old_rel_targets.py kitp2 src/0762effe61de88c0.db1 13 id1 2>&1 | cut -c1-400 | head -20
