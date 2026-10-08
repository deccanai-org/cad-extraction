#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
/opt/conv/ifc84/bin/python tools/child_rec.py kitp src/0762effe61de88c0.db1 2>&1 | head -c 15000
