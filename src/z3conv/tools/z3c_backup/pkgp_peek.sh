#!/bin/bash
ps -eo pid,etime,pcpu,rss,args | grep -E "pkgpartial|python -$" | grep -v grep | cut -c1-150 | head; ls -la /opt/pkgpartial/out/ 2>/dev/null
