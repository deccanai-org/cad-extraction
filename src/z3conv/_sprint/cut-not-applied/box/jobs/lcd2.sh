#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
timeout 600 /opt/conv/ifc84/bin/python tools/lc_dump.py 0762effe61de88c0 57982 25391 2>&1 | grep -v "at (v,w)=(\(-50,0\|0,-50\|-50,-50\|50,50\))"
