#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
sort -k4 -n -r census.log | head -12; echo; cat reg.log | tail -12
