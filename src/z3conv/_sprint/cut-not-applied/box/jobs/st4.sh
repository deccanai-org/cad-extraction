#!/bin/bash
cd /work/agentwork/cut-not-applied; tail -c 600 pipes3/fit/truth_iron/val.log; echo; ps -eo pid,etime,pcpu,rss,cmd | grep "[t]ruth_iron" | cut -c1-160
