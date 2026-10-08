#!/bin/bash
W=/work/agentwork/coverage-regression
echo "my processes:"; ps -eo pid,etime,args | grep -E "coverage-regression|run_wj.py|ab_one.py|ab_run.sh|abj_run.sh|probe[0-9]?\.py|probe_profdb" | grep -v grep | cut -c1-160
du -sh $W 2>/dev/null
# drop per-model work dirs (STEP / IFC copies); keep result JSONs, kits, logs
for t in dec_i dec_fix dec_j dec_jfix full_fix; do find $W/ab/$t -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} + 2>/dev/null; done
du -sh $W 2>/dev/null; ls $W/ab | head -40
