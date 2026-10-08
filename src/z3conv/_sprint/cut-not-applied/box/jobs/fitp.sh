#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/fit_probe.py tools/
timeout 900 /opt/conv/env/bin/python tools/fit_probe.py gsk 2>&1 | cut -c1-900
