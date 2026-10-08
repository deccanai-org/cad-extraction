#!/bin/bash
uptime; systemctl is-active z3coord z3status z3pkg-verify2; tail -3 /opt/z3c/index.log | cut -c1-300; ls -la /opt/z3c/index.log /opt/z3c/index-zentitude-data-4.log; ps -eo pid,etime,pcpu,rss,args --sort=-pcpu | head -8 | cut -c1-200; tail -2 /opt/pkgverify2_r1/log.txt
