#!/bin/bash
cd /work/agentwork/cut-not-applied; for d in pipes2/kit2/5b33936fcd1e3efc pipes2/kitp2/5b33936fcd1e3efc pipes2/kit2/dcdf359ef4a2499b pipes2/kitp2/dcdf359ef4a2499b; do echo "$d: $(ls $d | tr '\n' ' ' | cut -c1-200)"; tail -c 300 $d/log.txt | tr '\n' ' ' | cut -c1-300; echo; done
ps -eo pid,etime,pcpu,rss,cmd | grep "[5]b33\|[d]cdf" | cut -c1-180
