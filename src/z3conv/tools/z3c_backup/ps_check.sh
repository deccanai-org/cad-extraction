#!/bin/bash
# READ-ONLY: coordinator process / memory snapshot (census, job builder, index rounds)
ps -eo pid,etime,pcpu,rss,args --sort=-pcpu | grep -E "zjobs|zcensus|zresidual|build_index" | grep -v grep | cut -c1-160
free -g | head -2; nproc; uptime
