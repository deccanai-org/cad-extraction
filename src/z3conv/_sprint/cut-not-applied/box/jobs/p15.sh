#!/bin/bash
# P15 check: kitnp8 (= kitnp7 + P15) on IRON_ORE vs its Tekla IFC (section bbox / centroid per part, NetVolume)
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
rm -rf kitnp8; cp -r kitn kitnp8; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp8 > res/patch_kitnp8.txt 2>&1 && touch kitnp8/.patched; tail -1 res/patch_kitnp8.txt
md5sum kitnp8/db1old.py kitnp8/db1dec.py kitnp8/db1step.py kitnp8/fittings.py > res/kitnp8.md5; aws s3 cp --quiet res/kitnp8.md5 $OUT/final/
O=pipes5/kitnp8/truth_iron; [ -f $O/pipe.json ] || bash tools/pipe.sh $W/kitnp8 truth_iron $W/$O
timeout 2400 /opt/conv/env/bin/python tools/bbox_truth.py iron $O 3000 > res/bbox_p15_iron.txt 2>&1; aws s3 cp --quiet res/bbox_p15_iron.txt $OUT/final/
until [ -f pipes5/kitnp7/truth_iron/pipe.json ] && [ -f pipes5/kitn/truth_iron/pipe.json ]; do sleep 30; done
KIT=$W/kitnp8 /opt/conv/env/bin/python tools/truth_cmp2.py iron coden=pipes5/kitn/truth_iron p1_14=pipes5/kitnp7/truth_iron p1_15=$O > res/truth_p15_iron.txt 2>&1; aws s3 cp --quiet res/truth_p15_iron.txt $OUT/final/
echo P15DONE
