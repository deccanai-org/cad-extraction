#!/bin/bash
# read-only: 6.1.11 canary unit state and log tail on this box
for L in rc ctl; do echo "== $L $(systemctl is-active z3canary-ifc6111$L) ok=$(grep -c ' ok ' /opt/conv/canary/ifc6111$L/worker.log 2>/dev/null)"; tail -n 4 /opt/conv/canary/ifc6111$L/worker.log 2>/dev/null | cut -c1-220; done; uptime
