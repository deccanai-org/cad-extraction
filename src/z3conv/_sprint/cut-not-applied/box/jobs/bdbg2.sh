#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/bool_dbg2.py tools/
timeout 300 /opt/conv/env/bin/python tools/bool_dbg2.py pipes2/kitp2/6eabb07e71459be6/model.ifc '0tlg$4Lxf3yhKx$UU2CNuB' 2>&1 | cut -c1-400
