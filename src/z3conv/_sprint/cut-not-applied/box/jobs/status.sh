#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
uptime; ls dec/before 2>/dev/null | grep -c json; ls dec/after 2>/dev/null | grep -c json; ls -la res/trace 2>/dev/null
tail -3 logs/*.log 2>/dev/null | tail -20
ps aux | grep -c "[t]ools/"
