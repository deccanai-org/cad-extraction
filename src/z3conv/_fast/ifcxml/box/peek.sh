#!/bin/bash
cd /work/agentwork/ifcxml
uptime
cat job.log; echo "-- tests.log"; tail -c 6000 tests.log; echo "-- find.log"; tail -n 15 find.log 2>/dev/null; echo "-- conv_d4.log"; tail -n 20 conv_d4.log 2>/dev/null
ps -eo pid,pcpu,rss,etime,args --sort=-pcpu | grep -E "agentwork/ifcxml|ifcxml2spf|validate_spf|find_inputs|conv_batch|ifc2step6.py|step_check|ifc_census" | grep -v grep | head -20 | cut -c1-220
