#!/bin/bash
# ifcxml job 2: final converter (v1.1.0) re-conversion + validation of all data-4 inputs, SPF DATA-section identity vs the
# first run, then the PATCHED fleet worker end to end (harness, uploads redirected to agentwork)
cd /work/agentwork/ifcxml
P=/opt/conv/env/bin/python
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
echo $$ > job2.pid
log() { echo "$(date -u +%FT%TZ) $*" >> job2.log; aws s3 cp job2.log $OUT/logs/job2.log --only-show-errors; }
log start
while [ ! -f job.done ]; do sleep 20; done
log "job1 done"
cat > datasha.py <<'PY'
import sys, json, glob, hashlib, os
def data_sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        buf = f.read(1 << 20); i = buf.find(b'\nDATA;\n'); h.update(buf[i:] if i >= 0 else buf)
        for blk in iter(lambda: f.read(1 << 22), b''): h.update(blk)
    return h.hexdigest()
print(json.dumps({os.path.basename(p)[:-4]: [data_sha(p), os.path.getsize(p)] for p in sorted(glob.glob(sys.argv[1] + '/*/*.ifc'))}, indent=1))
PY
$P datasha.py work/conv > spf_v10.json
for f in ifcxml2spf.py validate_spf.py conv_batch.py worker_harness.py jobs_harness.json worker_patched.py worker_ifcxml.diff; do
  aws s3 cp $CTL/agentjobs/ifcxml/$f $f --only-show-errors; done
log "code fetched: $(grep -m1 "^VERSION" ifcxml2spf.py)"
CONV_OUT=cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/v11 $P conv_batch.py jobs_d4.json --procs 4 --no-step --tag d4v11 --workdir work/conv_v11 > conv_d4v11.log 2>&1
$P datasha.py work/conv_v11 > spf_v11.json
$P - <<'PY' > spf_identity.json
import json
a = json.load(open('spf_v10.json')); b = json.load(open('spf_v11.json'))
print(json.dumps({'compared': len(set(a) & set(b)), 'identical_data_sections': sorted(k for k in a if k in b and a[k][0] == b[k][0]),
                  'different': sorted(k for k in a if k in b and a[k][0] != b[k][0]), 'v10': a, 'v11': b}, indent=1))
PY
aws s3 cp spf_identity.json $OUT/spf_identity_v10_v11.json --only-show-errors
log "v11 conversions done: $(grep -c done conv_d4v11.log)"
# harness: kit exactly as published + the patched worker + ifcxml2spf.py
rm -rf hx && mkdir -p hx/kit
aws s3 cp --recursive $CTL/ifc/ hx/kit/ --exclude "*/*" --only-show-errors
orig=$(md5sum hx/kit/worker.py | cut -d' ' -f1)
if [ "$orig" = "652dd1000f10faa77cd6a95b86d2e755" ]; then cp worker_patched.py hx/kit/worker.py; log "kit worker.py unchanged since snapshot: patched copy installed";
else patch hx/kit/worker.py < worker_ifcxml.diff && log "kit worker.py changed ($orig): diff applied" || log "PATCH FAILED on changed worker $orig"; fi
cp ifcxml2spf.py hx/kit/
cd hx && IFC_THREADS=2 $P ../worker_harness.py kit ../jobs_harness.json --procs 3 > ../harness.log 2>&1; cd ..
aws s3 cp harness.log $OUT/logs/harness.log --only-show-errors
log "harness done"
touch job2.done
