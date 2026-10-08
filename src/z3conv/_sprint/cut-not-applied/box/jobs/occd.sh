#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/occ_dump.py tools/
timeout 600 /opt/conv/ifc84/bin/python tools/occ_dump.py kitp3 src/0762effe61de88c0.db1 956 24964 2>&1 | cut -c1-400
