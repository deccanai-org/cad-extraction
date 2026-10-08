#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/part_rels.py tools/
timeout 600 /opt/conv/ifc84/bin/python tools/part_rels.py kitp3 src/0762effe61de88c0.db1 'L150*90*10' 1500 2>&1 | cut -c1-330 | head -80
