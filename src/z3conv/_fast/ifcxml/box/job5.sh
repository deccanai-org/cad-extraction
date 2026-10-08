#!/bin/bash
# ifcxml job 5: final validator - regression suite + re-validation of the data-4 inputs with converter v1.1.1
cd /work/agentwork/ifcxml
P=/opt/conv/env/bin/python
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml
echo $$ > job5.pid
log() { echo "$(date -u +%FT%TZ) $*" >> job5.log; aws s3 cp job5.log $OUT/logs/job5.log --only-show-errors; }
log start
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml/validate_spf.py validate_spf.py --only-show-errors
cp validate_spf.py t2/validate_spf.py; cp ifcxml2spf.py t2/ifcxml2spf.py
(cd t2 && rm -rf work && bash run_tests.sh > tests_final.log 2>&1)
aws s3 cp t2/work/tests/summary.json $OUT/tests_summary_final.json --only-show-errors
log "tests: $(tail -1 t2/tests_final.log)"
CONV_OUT=cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/final $P conv_batch.py jobs_d4.json --procs 4 --no-step --tag d4final --workdir work/conv_final > conv_d4final.log 2>&1
$P datasha.py work/conv_final > spf_final.json
$P - <<'PY' > spf_identity_final.json
import json
a = json.load(open('spf_v10.json')); b = json.load(open('spf_final.json'))
print(json.dumps({'compared': len(set(a) & set(b)), 'identical_data_sections': sorted(k for k in a if k in b and a[k][0] == b[k][0]),
                  'different': sorted(k for k in a if k in b and a[k][0] != b[k][0]), 'final': b}, indent=1))
PY
aws s3 cp spf_identity_final.json $OUT/spf_identity_v10_final.json --only-show-errors
log "final conversions: $(grep -c ' done ' conv_d4final.log); identical data sections: $(grep -c '_' spf_identity_final.json)"
log "job5 done"
