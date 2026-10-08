#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/endoff_probe.py tools/; timeout 1200 /opt/conv/env/bin/python tools/endoff_probe.py iron 2>&1 | cut -c1-600
