#!/bin/bash
hostname; nproc; uptime; free -g | head -2; df -h /work 2>/dev/null | tail -1
ls /work/agentwork 2>/dev/null
/opt/conv/env/bin/python -c "import scipy, numpy, ifcopenshell; print('scipy', scipy.__version__, 'numpy', numpy.__version__, 'ifcos', ifcopenshell.version)" 2>&1
/opt/conv/env/bin/python -c "import OCC; from OCC.Core.STEPControl import STEPControl_Reader; print('occ ok')" 2>&1
ps -eo pid,user,pcpu,rss,etime,cmd --sort=-pcpu | head -15
