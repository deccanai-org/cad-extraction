#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
timeout 1500 /opt/conv/ifc84/bin/python tools/a944_probe.py kitp src/a94442572f225f50.db1 2>&1 | cut -c1-600
