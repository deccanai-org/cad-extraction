#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
uptime; ls /work/agentwork/
ps -eo pid,ppid,nlwp,pcpu,rss,etime,args --sort=-pcpu | head -30 | cut -c1-180
ls -la nc_find.json 2>&1; tail -5 census.log
