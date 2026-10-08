#!/bin/bash
for u in z3canary-rc z3canary-base2; do echo "$u $(systemctl is-active $u)"; done
tail -n 5 /opt/conv/canary/rc/worker.log 2>/dev/null | cut -c1-200
tail -n 5 /opt/conv/canary/base2/worker.log 2>/dev/null | cut -c1-200
uptime
