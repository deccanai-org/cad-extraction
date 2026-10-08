#!/bin/bash
hostname; uptime; free -g | head -2; df -h /work 2>/dev/null | tail -1; nproc
ls /work/agentwork/ 2>/dev/null
ps -eo pid,user,pcpu,rss,etime,args --sort=-rss | head -15 | cut -c1-200
/opt/conv/env/bin/python -c "import boto3,orjson,numpy;print('py ok')"
