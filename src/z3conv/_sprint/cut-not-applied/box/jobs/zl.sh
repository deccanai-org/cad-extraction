#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/zlage_truth.py tools/
timeout 1200 /opt/conv/env/bin/python tools/zlage_truth.py iron kit2 2>&1 | cut -c1-500
