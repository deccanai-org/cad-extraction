#!/bin/bash
ps -eo pid,pgid,etime,pcpu,rss,args --sort=etime | grep -E "harness2|runjob|fullpath" | grep -v grep | cut -c1-170
free -g | head -2
