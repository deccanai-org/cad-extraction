#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
uptime; ls census/kit_i/*.json | wc -l; ls census/kit_i/*.err 2>/dev/null | wc -l; tail -4 census.log; cat nc_find.log 2>/dev/null | tail -3; ls -la nc_find.json 2>/dev/null
