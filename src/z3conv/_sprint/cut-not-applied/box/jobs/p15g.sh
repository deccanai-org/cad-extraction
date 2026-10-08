#!/bin/bash
# P15 check on GAMBRO 7.24 (44k parts) vs its Tekla IFC: decoder + IFC writer only (code n vs kitnp8), section bbox per uncut part
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
until [ -f kitnp8/.patched ]; do sleep 10; done
for k in kitn kitnp8; do
  O=$W/ifconly/$k/truth_gambro; mkdir -p $O
  /opt/conv/ifc84/bin/python -c "import json; L=json.load(open('$W/$k/layouts.json')); json.dump(L['7.24'].get('layout'), open('$O/layout.json','w')); json.dump([v['layout'] for v in L.values() if v.get('layout')], open('$O/variants.json','w'))"
  [ -f $O/convert.json ] || OMP_NUM_THREADS=1 timeout 5400 /opt/conv/ifc84/bin/python $W/$k/convert_one.py src/truth_gambro.db1 $O/model.ifc $W/$k/tekla_profiles.json $O/layout.json $O/convert.json $O/variants.json > $O/log.txt 2>&1 &
done; wait
for k in kitn kitnp8; do KIT=$W/kitnp8 timeout 3600 /opt/conv/env/bin/python tools/bbox_truth.py gambro ifconly/$k/truth_gambro 8000 > res/bbox_p15_gambro_$k.txt 2>&1 & done; wait
for k in kitn kitnp8; do aws s3 cp --quiet res/bbox_p15_gambro_$k.txt $OUT/final/; done
echo P15GDONE
