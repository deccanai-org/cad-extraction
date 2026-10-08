#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
uptime; for k in kit_i kit_g kit_p; do echo "$k $(ls census/$k/*.json 2>/dev/null | wc -l) json $(ls census/$k/*.err 2>/dev/null | wc -l) err"; done
tail -3 reg.log; tail -3 full.log 2>/dev/null; ps -eo pid,etime,args | grep -E "harness2|fullpath|ifc2step|convert_one|step_check" | grep -v grep | wc -l
