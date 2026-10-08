#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/a944_hit.py tools/; /opt/conv/env/bin/python -c "import scipy" 2>&1 | head -1
timeout 1500 /opt/conv/env/bin/python tools/a944_hit.py 2>&1 | tail -8 | cut -c1-600
