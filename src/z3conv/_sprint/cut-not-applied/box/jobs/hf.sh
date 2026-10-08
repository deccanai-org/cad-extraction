#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/
timeout 900 /opt/conv/ifc84/bin/python tools/hot_fit.py 0762effe61de88c0 pipes3/nofit/0762effe61de88c0 pipes3/fit/0762effe61de88c0 $W/kitnp4 2>&1 | cut -c1-420 | tail -45
