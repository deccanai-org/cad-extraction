#!/bin/bash
# read-only: progress of the data-4 packaging dry run
systemctl status z3pkg-d4dry --no-pager 2>/dev/null | sed -n 1,12p | cut -c1-160
ps -eo pid,etimes,pcpu,rss,args | grep "pkg.py disk-dryrun" | grep -v grep | cut -c1-160
ls -la /opt/pkgdr | tail -5; df -h /opt | tail -1
