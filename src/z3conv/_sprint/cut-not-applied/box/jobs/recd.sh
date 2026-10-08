#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/rec_dump.py tools/
timeout 600 /opt/conv/ifc84/bin/python tools/rec_dump.py kitp3 src/0762effe61de88c0.db1 957 958 961 962 24965 24966 24969 24970 2>&1 | cut -c1-330
