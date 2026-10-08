#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/unwritten_parents.py tools/
timeout 900 /opt/conv/ifc84/bin/python tools/unwritten_parents.py c8d753af86305a39 ea1a25eb296ba2e7 148a5d4883dbbe24 8ebd3570ad53a76f 2>&1 | cut -c1-700
