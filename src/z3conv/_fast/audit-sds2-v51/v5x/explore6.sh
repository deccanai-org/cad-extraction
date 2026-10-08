#!/bin/bash
cd /work/agentwork/audit-sds2-v5x/code
ls; ls v5.3 | head; 
P=v5.3/sds2-step-pipeline
grep -rn "reference_open_shells\|reference_part_no_closed_brep\|open surface, not a closed solid" $P --include=*.py | head -30
echo ---- diff v5.2 v5.3 files
diff -rq v5.2/sds2-step-pipeline v5.3/sds2-step-pipeline | head; 
diff -rq v5.1/sds2-step-pipeline v5.2/sds2-step-pipeline | head
