#!/bin/bash
cd /work/agentwork/cut-not-applied; cp stage/tools/*.py tools/
export PIPE_A=pipes2/kit2 PIPE_B=pipes2/kitp3
/opt/conv/env/bin/python tools/hot_diff.py e151a8faacbce446 | grep -v "^==\|^TOTAL"
/opt/conv/env/bin/python tools/hot_diff.py 575da79b6096c760 | grep -v "^==\|^TOTAL" | head -20
