#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/l2ev.py $W/job/l2ev.py
cat > $W/diag/run_l2ev.sh <<'EOS'
W=/work/agentwork/ifc-verification-residue; P=/opt/conv/env/bin/python
mkdir -p $W/diag/l2ev
for d in mnc_dev3/4f6b8e2e96937507 mnc_dev3/944bc6d8f919e848 mnc_dev3/7b35850cd279e675 mnc_dev3/4bbcc615d753f653 l2_dev3/e4901c30087bbaec; do
  id=$(basename $d)
  IFC=$W/diag/l2ev/$id.ifc
  $P - "$W/in/$id.bin" "$IFC" <<'PY'
import sys, zipfile, gzip, shutil
src, dst = sys.argv[1], sys.argv[2]
h = open(src, 'rb').read(4)
if h[:2] == b'PK':
    z = zipfile.ZipFile(src); m = max(z.infolist(), key=lambda i: i.file_size)
    with z.open(m) as a, open(dst, 'wb') as b: shutil.copyfileobj(a, b, 1 << 24)
elif h[:2] == b'\x1f\x8b':
    with gzip.open(src) as a, open(dst, 'wb') as b: shutil.copyfileobj(a, b, 1 << 24)
else:
    shutil.copyfile(src, dst)
PY
  timeout 1500 $P $W/job/l2ev.py $W/w/$d $IFC $W/diag/l2ev/$id.jsonl --max 40 > $W/diag/l2ev/$id.log 2>&1
  rm -f $IFC
done
echo done > $W/diag/l2ev/DONE
aws s3 cp --quiet --recursive $W/diag/l2ev/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/l2ev/
EOS
rm -f $W/diag/l2ev/DONE
setsid nohup bash $W/diag/run_l2ev.sh > /dev/null 2>&1 < /dev/null &
echo started
