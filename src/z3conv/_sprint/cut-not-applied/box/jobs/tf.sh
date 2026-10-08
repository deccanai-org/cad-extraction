#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for n in iron gsk; do KIT=$W/kitnp9 /opt/conv/env/bin/python tools/truth_cmp2.py $n coden=pipes5/kitn/truth_$n final=pipes5/kitnp9/truth_$n > res/truth_final_$n.txt 2>&1 & done
( KIT=$W/kitnp9 timeout 2400 /opt/conv/env/bin/python tools/bbox_truth.py iron pipes5/kitnp9/truth_iron 3000 > res/bbox_final_iron.txt 2>&1 ) &
( KIT=$W/kitnp9 timeout 2400 /opt/conv/env/bin/python tools/bbox_truth.py iron pipes5/kitn/truth_iron 3000 > res/bbox_coden_iron.txt 2>&1 ) &
( KIT=$W/kitnp9 timeout 1200 /opt/conv/env/bin/python tools/len_check.py 0762effe61de88c0 pipes5/kitn/0762effe61de88c0 pipes5/kitnp9/0762effe61de88c0 '[200*90*8*13.5' 'L150*90*10' 'L65*65*6' 'L50*50*6' 'L100*75*10' > res/lencheck_final_0762.txt 2>&1 ) &
wait
for f in truth_final_iron.txt truth_final_gsk.txt bbox_final_iron.txt bbox_coden_iron.txt lencheck_final_0762.txt; do aws s3 cp --quiet res/$f $OUT/final/; done
cat res/truth_final_iron.txt | cut -c1-1300; head -8 res/truth_final_gsk.txt | cut -c1-600; cat res/bbox_coden_iron.txt res/bbox_final_iron.txt | grep "^  \|^==" | cut -c1-300; cat res/lencheck_final_0762.txt
