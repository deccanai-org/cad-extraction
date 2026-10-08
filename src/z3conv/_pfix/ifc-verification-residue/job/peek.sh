#!/bin/bash
W=/work/agentwork/ifc-verification-residue
tail -5 $W/drive_x612_ppv.log; tail -3 $W/drive_x612_l2.log | cut -c1-300
pgrep -af "drive2.py|rc2.py|ifc2step6_612|step_check|step_verify_big|ifc_census" | grep ifc-verification | cut -c1-200
free -g | head -2; uptime
