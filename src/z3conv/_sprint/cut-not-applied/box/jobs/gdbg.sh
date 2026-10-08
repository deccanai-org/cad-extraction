#!/bin/bash
cd /work/agentwork/cut-not-applied && cp stage/tools/guid_dbg.py tools/ 2>/dev/null; timeout 300 /opt/conv/env/bin/python tools/guid_dbg.py 2>&1 | cut -c1-600
