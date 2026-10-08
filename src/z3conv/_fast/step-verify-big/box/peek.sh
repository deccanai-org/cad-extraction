#!/bin/bash
cd /work/agentwork/step-verify-big
tail -4 out/B2/s_x24.log 2>/dev/null; echo; tail -2 out/B1/full_a.log 2>/dev/null; uptime
ps -eo pid,pcpu,rss,etime,args --sort=-rss | grep -E "step_check|step_verify_big" | grep -v grep | head -5 | cut -c1-170
ps -eo user,pcpu,args --sort=-pcpu | head -40 | awk '{print $3}' | sort | uniq -c | sort -rn | head -5
