#!/bin/bash
W=/work/agentwork/ifc-verification-residue
ls -la $W/job/ | grep ifc2step6; md5sum $W/job/ifc2step6_vr9.py
tail -3 $W/drive_xvr_mnc.log | cut -c1-300
