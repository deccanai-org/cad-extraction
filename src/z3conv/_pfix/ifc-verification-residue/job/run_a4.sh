#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
cat > $W/diag/l2ev612.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/ifc-verification-residue; P=/opt/conv/env/bin/python; L=${1:-x612_l2}
while pgrep -f "drive2.py $L " > /dev/null; do sleep 20; done
mkdir -p $W/diag/l2ev_$L
cd $W/w/$L
for d in */; do
  id=${d%/}
  [ -f $id/out.step.parts.json ] || continue
  n=$($P -c "import json;print(sum(1 for p in json.load(open('$id/out.step.parts.json'))['parts'] if p['level']==2))")
  [ "$n" -gt 0 ] || continue
  echo "$id $n" >> $W/diag/l2ev_$L/list.txt
  (
  IFC=$W/diag/l2ev_$L/$id.ifc
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
  timeout 2400 $P $W/job/l2ev.py $W/w/$L/$id $IFC $W/diag/l2ev_$L/$id.jsonl --max 60 > $W/diag/l2ev_$L/$id.log 2>&1
  rm -f $IFC
  ) &
  while [ $(jobs -r | wc -l) -ge 4 ]; do sleep 2; done
done
wait
echo done > $W/diag/l2ev_$L/DONE
aws s3 cp --quiet --recursive $W/diag/l2ev_$L/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/l2ev_$L/
EOS
setsid nohup bash $W/diag/l2ev612.sh x612_l2 > $W/diag/l2ev612_x612_l2.log 2>&1 < /dev/null &
echo started $!
