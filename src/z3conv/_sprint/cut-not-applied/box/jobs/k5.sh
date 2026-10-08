#!/bin/bash
pkill -f "pipes4/fit/575da79b6096c760"; sleep 1; pkill -f "pipe.sh /work/agentwork/cut-not-applied/kitnp6 575da"; rm -rf /work/agentwork/cut-not-applied/pipes4/fit/575da79b6096c760
ps -eo pid,etime,cmd | grep "[5]75da79b" | cut -c1-140; echo ok
