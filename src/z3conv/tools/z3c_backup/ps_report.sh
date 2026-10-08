#!/bin/bash
ps -eo pid,etime,pcpu,rss,args | grep -E "rep_|python - |venv/bin/python" | grep -v grep | cut -c1-150; ls -la /opt/report/assets/join/three_ways.json 2>&1
