#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/lage_probe.py tools/
timeout 600 /opt/ifc84/bin/python 2>/dev/null; timeout 900 /opt/conv/ifc84/bin/python tools/lage_probe.py kitp3 src/e151a8faacbce446.db1 src/0762effe61de88c0.db1 truth/iron.db1 2>&1 | cut -c1-400
