#!/bin/bash
# cleanup of MY workdir only (results already in s3 agentwork/ifc-verification-residue); stops my watchdog
W=/work/agentwork/ifc-verification-residue
pgrep -af "drive.py|rc.py" | grep ifc-verification-residue | cut -c1-120
du -sh $W 2>/dev/null
find $W/w -name 'out.step' -delete 2>/dev/null
find $W/w -name '*.ifc' -delete 2>/dev/null
find $W/w -name 'in.bin' -delete 2>/dev/null
rm -rf $W/in $W/diag/seaport.ifc $W/diag/far2files $W/diag/gp/*.parts.jsonl.gz 2>/dev/null
pkill -f "ifc-verification-residue/job/wd.sh"
du -sh $W 2>/dev/null
