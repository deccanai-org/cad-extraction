#!/bin/bash
W=/work/agentwork/ifc-verification-residue
for i in $(seq 1 36); do
  n=0
  for f in $W/w/far_vr8/d713eae4bf9dd247/case.json $W/w/far_vr8F_gp/d713eae4bf9dd247/case.json $W/w/stockton_vr7/2c0f7a89ddf2d595/case.json; do [ -f $f ] && n=$((n+1)); done
  [ $n -ge 3 ] && break
  sleep 10
done
echo "ready $n"
