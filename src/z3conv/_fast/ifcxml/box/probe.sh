#!/bin/bash
uptime; nproc; free -g | head -2; df -h /work / 2>/dev/null | tail -2
ls /work/agentwork 2>/dev/null
ps -eo pid,user,pcpu,rss,etime,args --sort=-pcpu | head -12 | cut -c1-200
/opt/conv/env/bin/python -c "import ifcopenshell, OCC; print(ifcopenshell.version, OCC.VERSION)"
aws --version 2>&1 | head -1
