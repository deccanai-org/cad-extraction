#!/bin/bash
tail -c 600 /work/agentwork/ifc-verification-residue/w/seaport_vr9/log.txt; echo; ps -eo pid,rss,etimes,args | grep seaport_vr9 | grep -v grep | head -3 | cut -c1-100
