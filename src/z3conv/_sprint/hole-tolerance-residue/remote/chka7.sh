#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
ps -eo pid,etime,pcpu,rss,args | grep -E "a7f94f2edc0f|ifc2step6|step_check|convert_one" | grep -v grep | cut -c1-180
ls -la full/kit_jp5/a7f94f2edc0f/ 2>/dev/null; tail -2 full_v5.log; uptime
