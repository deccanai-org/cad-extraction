#!/bin/bash
# convonly.sh LABEL CONVERTER_FILE JOBS - converter only (no grading) over the test set, keeps stats + sidecar
LABEL=$1; CONVF=$2; JOBS=${3:-3}
W=/work/agentwork/ifcv6; cd $W; mkdir -p w/$LABEL
export V6_VERIFY_PROCS=3 DEFLECTION=0.005 ANG_DEFLECTION=0.6
/opt/conv/env/bin/python - "$LABEL" "$CONVF" "$JOBS" <<'PY'
import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
lab, conv, jobs = sys.argv[1], sys.argv[2], int(sys.argv[3])
W = '/work/agentwork/ifcv6'
ts = json.load(open(W + '/dev/testset.json'))
ts.sort(key=lambda o: -o['size'])
def one(o):
    i = o['id'][:16]; d = '%s/w/%s/%s' % (W, lab, i); os.makedirs(d, exist_ok=True)
    if os.path.exists(d + '/out.step.stats.json'): return
    subprocess.run(['/opt/conv/env/bin/python', W + '/dev/' + conv, W + '/in/%s.bin' % i, d + '/out.step', '--mode', 'hybrid', '--prec', '2', '--threads', '2'],
                   stdout=open(d + '/stdout.txt', 'w'), stderr=open(d + '/log.txt', 'w'))
    try: os.remove(d + '/out.step')
    except OSError: pass
with ThreadPoolExecutor(jobs) as ex: list(ex.map(one, ts))
print('done')
PY
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcv6/$LABEL
for d in w/$LABEL/*/; do id=$(basename $d); for f in out.step.stats.json out.step.parts.json; do [ -f $d/$f ] && aws s3 cp --quiet $d/$f $R/$id/$f; done; done
echo uploaded > w/$LABEL.done
