#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for L in far_vr4 far_vr4B_gp far_vr5 far_vr5B_gp; do d=$W/w/$L/d713eae4bf9dd247; echo "== $L $(ls $d/case.json 2>/dev/null)"; grep -v "^\$ " $d/log.txt 2>/dev/null | tail -2 | cut -c1-200; done
pgrep -af "step_check|ifc_census" | grep ifc-verification | cut -c1-150
