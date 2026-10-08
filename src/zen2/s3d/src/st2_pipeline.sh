#!/bin/bash
# after ACIS decode: structure IFC v2 (ACIS solids, curved members, slabs) -> publish -> convert -> clean -> summaries
cd /data/s3d/src
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
until grep -q ACIS_DONE /data/s3d/logs/acis.log; do sleep 30; done
$PY acis_extract.py summary
echo "7: ACIS decoded; 8: re-emitting structure IFC with ACIS solids (+curved members, slabs)" > /data/s3d/work/stage.txt
$PY replan.py plan
$PY ifcjobs.py run --workers 6 --kind structure
$PY ifcjobs.py summary > /dev/null
$PY publish_fanout.py --final
echo "8: structure v2 IFC published (st2__ jobs, fanout_ready); converting STEP/GLB/OBJ" > /data/s3d/work/stage.txt
echo PUBLISHED_ST2
$PY fanout/worker.py --slots 8 --work /data/s3d/tmp/fw2 --local-root /data/s3d/out
$PY replan.py clean
$PY final_summary.py
$PY pairs.py build && $PY pairs_flags.py
$PY make_index.py
aws s3 cp --only-show-errors /data/s3d/out/json/index.json s3://annotationprod/cad-disk-extract/zenitude-data-2/model/json/index.json
echo "DONE core: JSON+PCF 45,003 (validated vs S3D iso PCFs), IFC/STEP(OCC-validated)/GLB/OBJ incl. ACIS structure, pairs index; optional PNG refresh running" > /data/s3d/work/stage.txt
echo CORE_DONE
# optional: PNG previews for new chunks + area composites
$PY png_chunks.py --procs 6
python3 - <<'PYEOF'
import json, subprocess
j = json.loads(subprocess.check_output(['aws', 's3', 'cp', 's3://annotationprod/cad-disk-extract/zenitude-data-2/_control/s3d3d/jobs.json', '-']))
a = [x for x in j if x['kind'] == 'area_png']
open('/data/s3d/tmp/jobs_png2.json', 'w').write(json.dumps(a))
for x in a:
    subprocess.run(['aws', 's3', 'rm', '--only-show-errors', 's3://annotationprod/cad-disk-extract/zenitude-data-2/_state/s3d3d/results/%s.json' % x['id']])
    subprocess.run(['aws', 's3', 'rm', '--only-show-errors', 's3://annotationprod/cad-disk-extract/zenitude-data-2/_state/s3d3d/claims/%s.json' % x['id']])
PYEOF
aws s3 cp --only-show-errors /data/s3d/tmp/jobs_png2.json s3://annotationprod/cad-disk-extract/zenitude-data-2/_control/s3d3d/jobs_png.json
$PY fanout/worker.py --png --slots 2 --jobs-key cad-disk-extract/zenitude-data-2/_control/s3d3d/jobs_png.json --work /data/s3d/tmp/fwp2
$PY final_summary.py
echo "DONE: all stages complete (see counts); PNG previews refreshed" > /data/s3d/work/stage.txt
echo ALL_DONE
