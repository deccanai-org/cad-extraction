#!/bin/bash
# ifcxml job 4: final converter v1.1.1 (header-only change) - re-conversion + validation of the data-4 inputs, DATA-section
# identity vs the first run, regression suite
cd /work/agentwork/ifcxml
P=/opt/conv/env/bin/python
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
echo $$ > job4.pid
log() { echo "$(date -u +%FT%TZ) $*" >> job4.log; aws s3 cp job4.log $OUT/logs/job4.log --only-show-errors; }
log start
while [ ! -f job3.done ]; do sleep 15; done
aws s3 cp $CTL/agentjobs/ifcxml/ifcxml2spf.py ifcxml2spf.py --only-show-errors
log "version $(grep -m1 '^VERSION' ifcxml2spf.py)"
CONV_OUT=cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/v111 $P conv_batch.py jobs_d4.json --procs 4 --no-step --tag d4v111 --workdir work/conv_v111 > conv_d4v111.log 2>&1
$P datasha.py work/conv_v111 > spf_v111.json
$P - <<'PY' > spf_identity_v111.json
import json, glob
a = json.load(open('spf_v10.json')); b = json.load(open('spf_v111.json'))
hdr = {}
for p in sorted(glob.glob('work/conv_v111/*/*.ifc')):
    with open(p, errors='replace') as f:
        h = f.read(4096)
    hdr[p.split('/')[-1][:-4]] = h[:h.find('DATA;')].strip().splitlines()[2:6]
print(json.dumps({'compared': len(set(a) & set(b)), 'identical_data_sections': sorted(k for k in a if k in b and a[k][0] == b[k][0]),
                  'different': sorted(k for k in a if k in b and a[k][0] != b[k][0]), 'headers_v111': hdr}, indent=1))
PY
aws s3 cp spf_identity_v111.json $OUT/spf_identity_v10_v111.json --only-show-errors
log "v111 conversions: $(grep -c ' done ' conv_d4v111.log) identity: $(grep -c '"' spf_identity_v111.json)"
cp ifcxml2spf.py t2/ifcxml2spf.py
(cd t2 && rm -rf work && bash run_tests.sh > tests_v111.log 2>&1)
aws s3 cp t2/work/tests/summary.json $OUT/tests_summary_v111.json --only-show-errors
log "tests: $(tail -1 t2/tests_v111.log)"
log "job4 done"
touch job4.done
