#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for L in far_vr4 far_vr4B_gp; do
  for p in $(pgrep -f "drive.py $L "); do kill -9 $p; done
  for p in $(pgrep -f "ifc-verification-residue/w/$L/"); do kill -9 $p; done
  for p in $(pgrep -f "rc.py .*w/$L/"); do kill -9 $p; done
done
# stop only the ppv_vr3 driver (no new models); its two running cases continue
for p in $(pgrep -f "drive.py ppv_vr3 "); do kill -9 $p; done
sleep 1; pgrep -af "drive.py" | cut -c1-95; pgrep -af "rc.py" | cut -c1-140; uptime
