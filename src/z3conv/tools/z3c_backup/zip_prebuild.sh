#!/bin/bash
# Pre-build the remaining SDS2 job zips of ONE partial package across the fleet (owner: finish fast). Each box takes the zips in its own
# random order, skips any already uploaded, builds with the packager's own build_zip and uploads exactly like apply_plan (same metadata),
# so the coordinator's job reuses them. A zip built twice has identical bytes. 4 processes per box.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/zipprebuild; mkdir -p $D/kit $D/work
if systemctl is-active -q z3zipprebuild; then echo "running: built $(grep -c BUILT $D/log.txt) skipped $(grep -c SKIP $D/log.txt)"; exit 0; fi
avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo); [ "$avail" -lt 100 ] && { echo "skip: ${avail} GB free"; exit 0; }
for f in pkgcore.py pkg.py adapter_zen3.py adapter_zen4.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/$f $D/kit/$f || { echo "kit failed"; exit 1; }; done
MNT=$D/work; mountpoint -q /scratch && { mkdir -p /scratch/zipprebuild; MNT=/scratch/zipprebuild; }
cat > $D/pre.py <<'PYEOF'
import os, sys, json, gzip, random, socket, time, datetime
sys.path.insert(0, '/opt/zipprebuild/kit')
from multiprocessing import Pool
import pkgcore as pc
assert pc.TIER == 'partial'
PID = 'Zenitude-data-3__Completed_Projects_Data_0001Server13_Projects_05-11-2017_027_MMW Inc.7z'
WORK = sys.argv[1]
def log(*a): print(datetime.datetime.utcnow().strftime('%H:%M:%S'), *a, flush=True)
objs = pc.s3c().list_objects_v2(Bucket=pc.BUCKET, Prefix=f'{pc.PSTATE}/plans/{PID}/').get('Contents') or []
plan = pc.get_json(pc.BUCKET, max(objs, key=lambda o: o['LastModified'])['Key'])
base = plan['dest_prefix'].rstrip('/'); zips = plan['sds2_zips']
log('plan zips', len(zips))
def one(i):
    z = zips[i]; dst = f"{base}/{z['relpath']}"
    h = pc.head(pc.BUCKET, dst)
    if h and (h.get('Metadata') or {}).get('members-digest') == z['members_digest']: return 'SKIP'
    path, sha, n = pc.build_zip(z, os.path.join(WORK, f'z{i}'))
    h = pc.head(pc.BUCKET, dst)
    if h and (h.get('Metadata') or {}).get('members-digest') == z['members_digest']:
        os.remove(path); return 'SKIP'
    pc.put_json(pc.BUCKET, f"{pc.PSTATE}/sds2_members/{PID}/{z['relpath'].rsplit('/', 1)[-1]}.json.gz",
                {'relpath': z['relpath'], 'job_root': z['job_root'], 'zip_sha256': sha, 'members': z['members'],
                 **({'members_missing': z['members_missing_all']} if z.get('members_missing_all') else {})}, gz=True)
    pc.s3c().upload_file(path, pc.BUCKET, dst, ExtraArgs={'ChecksumAlgorithm': 'SHA256', 'ContentType': 'application/zip',
                                                         'Metadata': {'sha256': sha, 'members-digest': z['members_digest']}})
    os.remove(path); log('BUILT', z['relpath'], n); return 'BUILT'
order = list(range(len(zips))); random.Random(socket.gethostname()).shuffle(order)
with Pool(4, maxtasksperchild=1) as pool:
    for r in pool.imap_unordered(one, order):
        if r == 'SKIP': print('SKIP', flush=True)
log('done')
PYEOF
systemctl reset-failed z3zipprebuild 2>/dev/null
systemd-run --unit=z3zipprebuild --collect --nice=5 --working-directory=$D/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_TIER=partial \
  --setenv=PKG_ZIP_THREADS=32 /bin/bash -c "/opt/conv/env/bin/python $D/pre.py $MNT >> $D/log.txt 2>&1; echo rc=\$? >> $D/log.txt"
sleep 30; echo "prebuild: $(systemctl is-active z3zipprebuild) mem ${avail}G"; tail -n 2 $D/log.txt | cut -c1-150
