CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box
OUT=s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2/re
mkdir -p /opt/v2/re && cd /opt/v2/re && aws s3 sync --quiet $CTL/code/ code/
cp /opt/v2/code/tekla_profiles.json code/ 2>/dev/null
PY=/opt/conv/env/bin/python
get() { [ -f "$2" ] || aws s3 cp --quiet "s3://bim-proprietary-data/$1" "$2"; }
python3 - <<'PY' > pairs.tsv
import json
k = json.load(open('/opt/v2/val_keys.json'))
for t in ('8.85_Amazon_IAD_192', '9.08_ASV_Brain_and_Spine', '8.85_TORAY', '9.08_I8973', '8.65_19058_Giorgi_USA', '7.64_E-45_Check'):
    if t in k: print(t + '\t' + k[t][0] + '\t' + k[t][1])
PY
while IFS=$'\t' read -r T D I; do
  ( get "$D" "$T.db1"; get "$I" "$T.ifc"; cd code; $PY probe28.py ../$T.db1 ../$T.ifc > ../$T.p28.txt 2>&1; $PY probe26.py ../$T.db1 >> ../$T.p28.txt 2>&1; cd ..; aws s3 cp --quiet $T.p28.txt $OUT/$T.p28.txt ) &
done < pairs.tsv
wait
echo done
