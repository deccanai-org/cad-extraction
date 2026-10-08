#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
timeout 100 /opt/conv/env/bin/python aggregate.py > out/aggregate_interim.txt 2>&1; tail -3 out/aggregate_interim.txt
grep -c . out/report.md
