uptime; nproc; free -g | head -2; df -h /work | tail -1
ls /work/agentwork 2>/dev/null | head -30
ps -eo pid,pcpu,rss,etime,args --sort=-pcpu | head -15 | cut -c1-200
/opt/conv/env/bin/python -c "import ifcopenshell, OCC; print(ifcopenshell.version, OCC.VERSION)"
