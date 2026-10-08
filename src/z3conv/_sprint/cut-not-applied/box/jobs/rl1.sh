#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/; mkdir -p reports/0762; cp -n stage/reports/0762/* reports/0762/ 2>/dev/null; ls reports | head
until [ -f kitnp4/.patched ]; do sleep 5; done
timeout 900 /opt/conv/ifc84/bin/python tools/rep_len.py 0762effe61de88c0 $W/kitnp4 2>&1 | tail -45
