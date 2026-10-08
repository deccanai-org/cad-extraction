#!/bin/bash
ps -eo pid,ppid,pgid,etime,cmd | grep "[c]onvall\|[c]onv_only\|[x]args -P" | cut -c1-170
