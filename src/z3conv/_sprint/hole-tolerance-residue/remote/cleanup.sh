#!/bin/bash
W=/work/agentwork/hole-tolerance-residue
if pgrep -f "$W|harness2.py|runjob.py models|runjob2.py models|fullpath.py kit_|nc_find.py|nc_check" > /dev/null; then echo "still running:"; pgrep -af "$W|harness2.py|runjob.py models|runjob2.py models|fullpath.py kit_" | cut -c1-120; exit 0; fi
du -sh $W 2>/dev/null; rm -rf $W; ls /work/agentwork/; df -h / | tail -1; uptime
