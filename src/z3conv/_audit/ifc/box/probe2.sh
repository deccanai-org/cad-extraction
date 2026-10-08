#!/bin/bash
uptime; free -g | head -2
ps -eo pid,pcpu,pmem,rss,etime,args --sort=-rss | grep -E 'graph.py|scan.py' | grep -v grep | head -8 | cut -c1-200
ls /work/agentwork/audit-ifc/out | wc -l
