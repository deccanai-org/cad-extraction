#!/bin/bash
W=/work/agentwork/ifc-verification-residue/sds2
cat $W/bg.log | tail -3; cat $W/jobs/332cb8a3d530bf3aba509ff9.fetch.json 2>/dev/null | cut -c1-200
o=$W/out/v5.5.3/332cb8a3d530bf3aba509ff9; ls -la $o 2>/dev/null; grep -v "^\*\|Transferr\|^ *$" $o/log.txt 2>/dev/null | tail -8 | cut -c1-250; cat $o/rc.txt $o/guard.txt 2>/dev/null
for p in $(pgrep -f "out/v5.5.3/332cb8a3"); do echo "pid $p rss $(awk '/VmRSS/{print $2}' /proc/$p/status) kB"; done
free -g | head -2
