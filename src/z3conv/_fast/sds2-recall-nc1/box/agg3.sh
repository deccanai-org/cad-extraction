#!/bin/bash
cd /work/agentwork/sds2-recall-nc1 && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/aggregate.py aggregate.py.new && mv aggregate.py.new aggregate.py
timeout 100 /opt/conv/env/bin/python aggregate.py > out/aggregate_interim.txt 2>&1; tail -2 out/aggregate_interim.txt
ls convres | wc -l; tail -2 logs/conv.log; tail -2 logs/pipe.log; uptime
