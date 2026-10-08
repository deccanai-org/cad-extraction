#!/bin/bash
ps -eo pid,ppid,etime,pcpu,rss,cmd | grep "[c]ut-not-applied" | grep -v "ps.sh" | cut -c1-220
uptime
