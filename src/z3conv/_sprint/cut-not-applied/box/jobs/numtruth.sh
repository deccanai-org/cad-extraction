#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/num_truth.py tools/; timeout 900 /opt/conv/env/bin/python tools/num_truth.py iron 2>&1 | cut -c1-400
