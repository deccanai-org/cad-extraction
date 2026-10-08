#!/bin/bash
cd /work/agentwork/hole-tolerance-residue
P=$(pgrep -f "bash job_v5_coord.sh" | head -1); if [ -n "$P" ]; then PG=$(ps -o pgid= -p $P | tr -d ' '); echo "killing my v5 pgid $PG ($(ps -o pid= -g $PG | wc -l) procs)"; kill -- -$PG; fi
sleep 3; pgrep -af "ifc2step6|fullpath|runjob2" | cut -c1-120; rm -rf full/kit_jp5/a7f94f2edc0f/m.ifc full/kit_jp5/a7f94f2edc0f/.v6tmp_*; free -g | head -2; uptime
aws s3 cp --quiet census_v5.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/hole-tolerance-residue/census_v5.log
aws s3 cp --quiet full_v5.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/hole-tolerance-residue/full_v5.log
du -sh /work/agentwork/hole-tolerance-residue
