#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
uptime; cat res/patch_kitp2.txt 2>/dev/null | tail -4; grep -h "^CODE" kit2/worker.py
grep -h "^done" logs/pipes2.log 2>/dev/null | cut -c1-200
for d in pipes2/*/*; do [ -f $d/pipe.json ] || echo "running $d $(ls $d 2>/dev/null | tr '\n' ' ' | cut -c1-120)"; done
tail -3 logs/pipes2.log
