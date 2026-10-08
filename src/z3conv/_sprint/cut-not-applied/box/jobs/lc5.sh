#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/len_check.py tools/
SHOW='F.B50X6' KIT=$W/kitnp9 timeout 1500 /opt/conv/env/bin/python tools/len_check.py 575da79b6096c760 pipes5/kitn/575da79b6096c760 pipes5/kitnp9/575da79b6096c760 'F.B50X6' 'F.B75X6' 2>&1 | head -50
