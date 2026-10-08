#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/probe_kernel.py $W/job/probe_kernel.py
cd $W/diag
/opt/conv/env/bin/python - <<'PY'
import zipfile, gzip, shutil
src='/work/agentwork/ifc-verification-residue/in/beeeacea7d2d7546.bin'; dst='/work/agentwork/ifc-verification-residue/diag/seaport.ifc'
h=open(src,'rb').read(4)
if h[:2]==b'PK':
    z=zipfile.ZipFile(src); m=max(z.infolist(), key=lambda i:i.file_size); print('zip member', m.filename, m.file_size)
    with z.open(m) as a, open(dst,'wb') as b: shutil.copyfileobj(a,b,1<<24)
elif h[:2]==b'\x1f\x8b':
    with gzip.open(src) as a, open(dst,'wb') as b: shutil.copyfileobj(a,b,1<<24)
else:
    shutil.copyfile(src,dst)
PY
ls -la $W/diag/seaport.ifc
rm -f $W/diag/probe_seaport.jsonl
setsid nohup /opt/conv/env/bin/python $W/job/probe_kernel.py $W/job/ifc2step6_dev3.py $W/diag/seaport.ifc $W/diag/probe_seaport.jsonl --limit-gb 40 --only-openings > $W/diag/probe_seaport.log 2>&1 < /dev/null &
echo started $!
