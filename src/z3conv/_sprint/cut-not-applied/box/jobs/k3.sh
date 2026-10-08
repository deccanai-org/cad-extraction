#!/bin/bash
for g in 2630830 2655578 2497070 2498911 1483304; do kill -- -$g 2>/dev/null; done; sleep 2
pkill -f "pipes2/kit2/5b33936fcd1e3efc" ; pkill -f "pipes2/kitp2/5b33936fcd1e3efc"; sleep 1
ps -eo pid,etime,rss,cmd | grep "[5]b33936fcd1e3efc\|[p]ipes2.sh" | cut -c1-150; free -g | head -2
