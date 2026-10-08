#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
ls -la --time-style=+%H:%M:%S census/kit_g/ census/kit_p/ | head -40; date -u +%H:%M:%S
ps -eo etime,args | grep "harness2" | grep -v grep | awk '{print $1, $4, substr($5,5,12)}' | sort | head -30
