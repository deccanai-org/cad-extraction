#!/bin/bash
# idle SDS2 box (owner OK 2026-10-05): power off -> instance-initiated shutdown = terminate
L=$(cut -d' ' -f1 /proc/loadavg); echo "load $L"; awk -v l=$L 'BEGIN{exit !(l<0.5)}' && { echo powering-off; shutdown -h +1; } || echo "busy, left running"
