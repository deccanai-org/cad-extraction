#!/bin/bash
hostname; uptime; nproc; free -g | head -2; df -h /work 2>/dev/null | tail -1
WD=/work/agentwork/sds2-grating-cylinders
ls -la $WD 2>&1 | head -30
ls $WD/jobs 2>&1
du -sh $WD/jobs/* 2>/dev/null
ls /work/agentwork/ 2>/dev/null
ls /work/agentwork/sds2v54/ 2>/dev/null | head; ls /work/agentwork/sds2v54/jobs /work/agentwork/sds2v54/jobs3 2>/dev/null | head -40
ps -eo pid,user,pcpu,rss,etime,args --sort=-pcpu | head -12 | cut -c1-180
