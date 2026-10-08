#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
uptime
grep -h "^done" logs/pipes1.log 2>/dev/null | cut -c1-250
for d in pipes/*/*; do [ -f $d/pipe.json ] || echo "running/pending $d $(ls $d 2>/dev/null | tr '\n' ' ' | cut -c1-150)"; done
