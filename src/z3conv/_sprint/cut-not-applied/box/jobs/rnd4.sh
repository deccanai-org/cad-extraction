#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/spec2.py stage/tools/render_pair.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
P=/opt/conv/env/bin/python
r() { $P tools/spec2.py "$1" "$2" $3 $4 renders/$5.json "$6" "$7" "$8" && timeout 900 $P tools/render_pair.py renders/$5.json renders/$5.png && aws s3 cp --quiet renders/$5.png $OUT/renders/final_$5.png; }
until [ -f pipes5/kitnp9/0762effe61de88c0/pipe.json ] && [ -f pipes5/kitn/0762effe61de88c0/pipe.json ]; do sleep 30; done
r pipes5/kitn/0762effe61de88c0 pipes5/kitnp9/0762effe61de88c0 65130 0 p13_0762_L150_linecuts 'code n: 17.09 kg' 'final (P13 line cuts): 14.56 kg' '0762effe 6.87 L150*90*10 (mark TA4100, Tekla net 14.5 kg, gross 17.0)'
r pipes5/kitn/0762effe61de88c0 pipes5/kitnp9/0762effe61de88c0 52418 0 p13_0762_channel_fitting 'code n' 'final (P13 oblique fittings: ends extended to the planes, clipped)' '0762effe 6.87 [200*90*8*13.5 52418: two oblique fittings, bolt holes kept'
until [ -f pipes5/kitnp9/truth_iron/pipe.json ] && [ -f pipes5/kitn/truth_iron/pipe.json ]; do sleep 30; done
r pipes5/kitn/truth_iron pipes5/kitnp9/truth_iron 130663016 0 p13_iron_pipe_fitting 'code n (L 663.2 mm)' 'final (P13 fittings; Tekla Length 687.5)' 'IRON_ORE 7.24 PIPE1-1/2SCH40 130663016'
r pipes5/kitn/truth_iron pipes5/kitnp9/truth_iron 121775453 0 p13_iron_W10X22_fitting 'code n (L 1447.8)' 'final (P13 fittings; Tekla Length 1412.9)' 'IRON_ORE 7.24 W10X22 121775453'
ls -la renders/*.png | tail
