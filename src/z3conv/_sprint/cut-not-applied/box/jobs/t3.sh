#!/bin/bash
cd /work/agentwork/cut-not-applied
for f in res/trace3_4fa8f263f754f862.txt res/trace3_cc9bf730baa1585c.txt res/trace3_27a9febf9f71d956.txt res/trace3_dcdf359ef4a2499b.txt res/numprof_dcdf359ef4a2499b.txt res/blopcl_a94442572f225f50.txt res/newsalv_a94442572f225f50.txt; do echo "#### $f"; head -c 2500 $f; echo; done
