#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
rm -rf kitp; cp -r kit kitp; cp stage/kitp/* kitp/
/opt/conv/ifc84/bin/python tools/objtype_probe.py kitp src/0762effe61de88c0.db1 src/6eabb07e71459be6.db1 src/172ffb7a9ab8a81d.db1 2>&1 | head -c 15000
