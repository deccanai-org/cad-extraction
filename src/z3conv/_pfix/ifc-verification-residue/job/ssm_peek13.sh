#!/bin/bash
W=/work/agentwork/ifc-verification-residue
ls -la $W/diag/gp/ | head -30
pgrep -af "step_check" | cut -c1-160
