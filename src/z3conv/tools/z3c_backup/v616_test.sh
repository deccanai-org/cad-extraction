#!/bin/bash
# ifc2step6 6.1.5 (live kit) vs 6.1.6: convert + in-place step_check + census + join coverage, 5 models
set -u
T=/opt/conv/scratch_v616; mkdir -p $T/src $T/k6; cd $T
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/test/ifc616/ifc2step6.py $T/k6/ifc2step6.py
K=/opt/conv/kit/ifc; PY=/opt/conv/env/bin/python
export OMP_NUM_THREADS=1
while read ID KEY; do
  [ -n "$KEY" ] || continue
  [ -s src/$ID.ifc ] || aws s3 cp --quiet "s3://bim-proprietary-data/$KEY" src/$ID.ifc
  ( timeout 3000 $PY $K/ifc_census.py src/$ID.ifc $T/$ID.census.json --parts $T/$ID.src.jsonl.gz > $T/$ID.census.log 2>&1 ) &
  for V in 615 616; do
    C=$K/ifc2step6.py; [ $V = 616 ] && C=$T/k6/ifc2step6.py
    ( cd $T && timeout 3000 systemd-run --scope --quiet -p MemoryMax=60G $PY $C src/$ID.ifc $T/$ID.$V.stp --mode hybrid --prec 2 --threads 4 > $T/$ID.$V.log 2>&1;
      timeout 3000 $PY $K/step_check.py $T/$ID.$V.stp $T/$ID.$V.chk.json --parts $T/$ID.$V.parts.jsonl.gz > $T/$ID.$V.chk.log 2>&1; rm -f $T/$ID.$V.stp ) &
  done
  wait
done <<LIST
7ec85dca81b918c9 cad-disk-extract/zenitude-data-3/extracted/Completed_Projects_Data_0105_Qualico Steel Co Inc_MT23_021.1 (Project Gateway-Boiler plant).7z/MT23_021.1 (Project Gateway-Boiler plant)/08. Uploads/For FAB/Transmittal 2306-653_Dated 07-12-2024/EM11 IFC File/2306_S21.6, 21.6M, 21.6MS _EM11.ifc
1ea774eb6201c3e1 cad-disk-extract/zenitude-data-3/extracted/Completed_Projects_Data_0105_Qualico Steel Co Inc_MT23_021.2 (Project Gateway-Fiberline)_08. Uploads.7z/08. Uploads/For FAB/Transmittal 2306-658_Dated 07-15-2024/EM11 IFC File/2306_S209.4(M & MS)_EM11_IFC.ifc
c8f3e1a6c10b3496 cad-disk-extract/zenitude-data-3/extracted/Completed_Projects_Data_0105_Qualico Steel Co Inc_MT23_021.2 (Project Gateway-Fiberline)_08. Uploads.7z/08. Uploads/For FAB/Transmittal 2306-743_Dated 08-23-2024/EM11 IFC File/2306_S501.1, 501.1BP, 501.1M & 501.1MS_EM11.ifc
0933b1c142111d94 cad-disk-extract/dataset/main/3d/Disk-2__Completed_Projects_Data_0001Server13_Projects_05-11-2017_027_MMW_Inc.7z/model/ifc/PVA_CRUSHING_JOB-1198c2.ifc
0813273195302651 cad-disk-extract/dataset/main/3d/Disk-2__Completed_Projects_Data_009_Geiger_Peters_MT18_137_16_Tech_-_Building_One_.7z/model/ifc/16_TECH_BUILDING_ONE_JOB-20017b.ifc
LIST
cat > $T/cmp.py <<'PY'
import json, sys, os
sys.path.insert(0, '/opt/conv/kit/ifc'); import grade_join
T = '/opt/conv/scratch_v616'
for ID in ["7ec85dca81b918c9", "1ea774eb6201c3e1", "c8f3e1a6c10b3496", "0933b1c142111d94", "0813273195302651"]:
    src = f'{T}/{ID}.src.jsonl.gz'
    for V in ('615', '616'):
        try:
            c = json.load(open(f'{T}/{ID}.{V}.chk.json'))
            j = grade_join.join(grade_join.load(src), grade_join.load(f'{T}/{ID}.{V}.parts.jsonl.gz')) if os.path.exists(src) else {}
            print(ID, V, 'read', c.get('read_status'), 'solids', c.get('solids'), 'invalid', c.get('invalid'), 'nonpos', c.get('nonpos_vol'), 'v6', c.get('v6_tags'),
                  'cov', {k: j.get(k) for k in ('coverage', 'step_parts') if k in j})
        except Exception as e:
            print(ID, V, 'ERR', type(e).__name__, str(e)[:120])
PY
/opt/conv/env/bin/python $T/cmp.py
