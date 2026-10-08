#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for d in far_vr8/d713eae4bf9dd247 far_vr8F_gp/d713eae4bf9dd247 stockton_vr7/2c0f7a89ddf2d595 ppv_vr4b/af3c44bd76cfb905 ppv_vr3/beeeacea7d2d7546; do echo "== $d $(ls $W/w/$d/case.json 2>/dev/null)"; grep -v '^\$ ' $W/w/$d/log.txt 2>/dev/null | tail -1 | cut -c1-160; done
pgrep -af "step_check|ifc_census" | grep ifc-verification | cut -c60-170; uptime
