#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/truth_cmp.py tools/
timeout 600 /opt/conv/env/bin/python tools/truth_cmp.py gsk 2>&1 | cut -c1-700
