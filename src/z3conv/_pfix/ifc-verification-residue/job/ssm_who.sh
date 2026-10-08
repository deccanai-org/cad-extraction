#!/bin/bash
ps -eo pid,etimes,args | grep "drive.py" | grep -v grep | cut -c1-200
ls -la /work/agentwork/ifc-verification-residue/ | head; ls /work/agentwork/ifc-verification-residue/w/
