#!/bin/bash
cd /work/agentwork/ifcxml
uptime; cat harness.log; echo "-- job3"; cat job3.log | cut -c1-200; echo "-- job4"; cat job4.log 2>/dev/null
ps -eo pid,pcpu,rss,etime,args --sort=-pcpu | grep -E "agentwork/ifcxml" | grep -v grep | head -8 | cut -c1-200
