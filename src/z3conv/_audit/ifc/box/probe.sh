#!/bin/bash
hostname; uptime; nproc; free -g | head -2; df -h /work 2>/dev/null | tail -1; df -h / | tail -1
echo "--- top procs"; ps -eo pid,ppid,pcpu,pmem,etime,args --sort=-pcpu | head -25 | cut -c1-220
echo "--- agentwork"; ls -la /work/agentwork 2>/dev/null
