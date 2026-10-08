#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/lc_dump.py tools/
timeout 600 /opt/conv/ifc84/bin/python tools/lc_dump.py 0762effe61de88c0 57982 25281 65130 194943 2>&1 | tail -60
