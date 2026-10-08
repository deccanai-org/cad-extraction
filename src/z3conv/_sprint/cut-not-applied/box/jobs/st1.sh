#!/bin/bash
cd /work/agentwork/cut-not-applied
ls -la logs | tail -30
for f in logs/fitp.log logs/endoff.log logs/a944hit.log logs/kitp5.log logs/p4518.log; do echo "=== $f"; tail -c 3500 $f 2>/dev/null; done
ls truth
