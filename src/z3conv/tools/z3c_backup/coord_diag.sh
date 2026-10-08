#!/bin/bash
# READ-ONLY coordinator diagnosis: services, round processes, last log lines, disk / memory.
uptime; df -h / | tail -1; free -g | head -2
echo "== services"; systemctl is-active z3coord z3status; systemctl status z3coord --no-pager 2>&1 | head -12
echo "== processes"; ps -eo pid,etime,pcpu,rss,args --sort=-etime | grep -E "build_index|coord|pkg|python" | grep -v grep | cut -c1-160 | head -15
echo "== index.log"; tail -n 6 /opt/z3c/index.log | cut -c1-300
echo "== index-zentitude-data-4.log"; tail -n 4 /opt/z3c/index-zentitude-data-4.log | cut -c1-300
echo "== coord journal"; journalctl -u z3coord --no-pager -n 15 2>&1 | cut -c1-250
