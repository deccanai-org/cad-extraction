#!/bin/bash
cd /work/agentwork/audit-sds2-v5x/code
P=v5.3/sds2-step-pipeline/decode
sed -n 880,935p $P/to_step2.py
echo ---- brep open
grep -n "def .*open\|allow_open\|open_ok\|def piece_shell\|def sew\|BRepBuilderAPI_Sewing" $P/brep.py | head -20
echo ---- diff v5.2 v5.3 to_step2
diff v5.2/sds2-step-pipeline/decode/to_step2.py v5.3/sds2-step-pipeline/decode/to_step2.py
