#!/bin/bash
hostname; uptime; nproc; free -g | head -3; df -h /work 2>/dev/null | tail -1; df -h / | tail -1
ls -la /work/agentwork/ 2>&1 | head -20
/opt/conv/env/bin/python -c "import OCC, numpy, sys; print('occ', OCC.VERSION, 'numpy', numpy.__version__, sys.version.split()[0])"
ps -eo pid,user,pcpu,rss,etime,args --sort=-pcpu | head -15 | cut -c1-200
aws --version 2>&1 | head -1
