#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
rm -rf kitp; cp -r kit kitp; cp stage/kitp/* kitp/
/opt/conv/ifc84/bin/python tools/attr_probe.py kitp src/0762effe61de88c0.db1 2>&1 | head -c 12000
