#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for L in far2_pfix far2_pfix_gp far2_pfixB_gp; do
  for p in $(pgrep -f "drive.py $L "); do kill -9 $p; done
  for p in $(pgrep -f "ifc-verification-residue/w/$L/"); do kill -9 $p; done
  for p in $(pgrep -f "rc.py .*w/$L/"); do kill -9 $p; done
done
sleep 2
pgrep -af "far2_" | cut -c1-120
uptime; free -g | head -2
