#!/bin/bash
# ifcxml job 3: the PATCHED fleet worker end to end on the data-4 ifcXML jobs (harness; uploads redirected to agentwork)
cd /work/agentwork/ifcxml
P=/opt/conv/env/bin/python
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
echo $$ > job3.pid
log() { echo "$(date -u +%FT%TZ) $*" >> job3.log; aws s3 cp job3.log $OUT/logs/job3.log --only-show-errors; }
log start
for f in apply_patch.py worker_harness.py jobs_harness.json ifcxml2spf.py; do aws s3 cp $CTL/agentjobs/ifcxml/$f $f --only-show-errors; done
rm -rf hx && mkdir -p hx/kit
aws s3 cp --recursive $CTL/ifc/ hx/kit/ --exclude "*/*" --only-show-errors
log "kit worker.py md5 $(md5sum hx/kit/worker.py | cut -d' ' -f1)"
$P apply_patch.py hx/kit/worker.py hx/kit/worker.patched.py >> job3.log 2>&1 && mv hx/kit/worker.patched.py hx/kit/worker.py || { log "PATCH FAILED"; touch job3.done; exit 1; }
cp ifcxml2spf.py hx/kit/
log "patched worker md5 $(md5sum hx/kit/worker.py | cut -d' ' -f1); $(ls hx/kit | tr '\n' ' ')"
cd hx && IFC_THREADS=2 $P ../worker_harness.py kit ../jobs_harness.json --procs 3 > ../harness.log 2>&1; cd ..
aws s3 cp harness.log $OUT/logs/harness.log --only-show-errors
log "harness done: $(tail -1 harness.log)"
touch job3.done
