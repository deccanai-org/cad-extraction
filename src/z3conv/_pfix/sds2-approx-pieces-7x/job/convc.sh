#!/bin/bash
# cand9 conversions (stage 2 --verify) on dirs_conv.txt (after/before table vs base553)
W=/work/agentwork/sds2-approx-pieces-7x
exec > $W/convc.log 2>&1
cd $W
pkill -f "$W/d7b.sh"
bash $W/mkvar553.sh cand9 cand9_brep.py:brep.py cand9_to_step2.py:to_step2.py
bash $W/conv_all.sh dirs_conv.txt "cand9" ${NP:-3} convc
