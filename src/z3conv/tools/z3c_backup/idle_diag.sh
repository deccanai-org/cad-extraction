#!/bin/bash
uptime; ls /opt/conv/ 2>/dev/null | head; ls -la /opt/conv/*.flag /opt/conv/FINAL* /opt/conv/DONE* 2>/dev/null
systemctl list-units --type=service --no-pager 2>/dev/null | grep -i -E "conv|z3|fleet" | head
ps -eo etime,args | grep -E "run.sh|convfleet|worker|python" | grep -v grep | cut -c1-160 | head
for f in /var/log/conv*.log /opt/conv/*.log /scratch/conv/*.log /scratch/conv/*/worker.log; do [ -f "$f" ] && { echo "== $f"; tail -n 6 "$f" | cut -c1-250; }; done 2>/dev/null | head -60
tail -n 30 /var/log/cloud-init-output.log 2>/dev/null | cut -c1-200
