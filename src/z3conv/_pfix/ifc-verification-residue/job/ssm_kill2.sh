#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for p in $(pgrep -f "ifc-verification-residue/w/ppv_dev3") $(pgrep -f "rc.py .*ifc-verification-residue/in/(1c61df42|2bcaa301|beeeacea)"); do kill -9 $p 2>/dev/null; done
sleep 2
pgrep -af "ppv_dev3|in/1c61df42|in/2bcaa301" | cut -c1-160
rm -rf $W/w/ppv_dev3/2bcaa3013d9250c2 $W/w/ppv_dev3/1c61df42e5270bac
ls $W/w/ppv_dev3/ ; pgrep -af "drive.py" | cut -c1-120
