#!/bin/bash
# stop the looping 6.1.11 canary units (lead 19:4xZ); nothing else touched
for L in rc ctl; do systemctl stop z3canary-ifc6111$L 2>/dev/null; echo "$L $(systemctl is-active z3canary-ifc6111$L) ok=$(grep -c ' ok ' /opt/conv/canary/ifc6111$L/worker.log 2>/dev/null)"; done
