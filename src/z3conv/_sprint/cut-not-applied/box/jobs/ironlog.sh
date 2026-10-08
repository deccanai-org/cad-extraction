#!/bin/bash
cd /work/agentwork/cut-not-applied; for v in kit2 kitp2 nc; do echo "== $v"; ls pipes2/$v/truth_iron/; tail -3 pipes2/$v/truth_iron/val.log 2>/dev/null; done; ps -eo pid,etime,pcpu,rss,cmd | grep "[t]ruth_iron" | cut -c1-200
