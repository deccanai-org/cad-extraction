#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/guid_dbg2.py tools/; timeout 600 /opt/conv/env/bin/python tools/guid_dbg2.py iron 2>&1 | cut -c1-400
