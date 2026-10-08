#!/bin/bash
cd /work/agentwork/audit-ifc
cat proofs2.log | tail -5; ls -la proofs2/; tail -c 1500 proofs2/check.log; ps -eo pid,etime,args | grep proofs2 | grep -v grep | cut -c1-150
